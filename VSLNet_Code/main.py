"""Main script to train/test models for Ego4D NLQ dataset.
"""
import argparse
import os

import numpy as np
import options
import torch
import torch.nn as nn
from torch.optim import AdamW 
import submitit
from torch.utils.tensorboard.writer import SummaryWriter
from model.VSLNet import build_optimizer_and_scheduler, VSLNet
from transformers import get_linear_schedule_with_warmup
from tqdm import tqdm
from utils.data_gen import gen_or_load_dataset
from utils.data_loader import get_test_loader, get_train_loader
from utils.data_util import load_json, load_video_features, save_json
from utils.runner_utils import (
    convert_length_to_mask,
    eval_test,
    filter_checkpoints,
    get_last_checkpoint,
    set_th_config,
)


def main(configs, parser):
    print(f"Running with {configs}", flush=True)

    # set tensorflow configs
    set_th_config(configs.seed)

    # prepare or load dataset
    dataset = gen_or_load_dataset(configs)
    configs.char_size = dataset.get("n_chars", -1)
    configs.word_size = dataset.get("n_words", -1)

    # get train and test loader
    visual_features = load_video_features(
        os.path.join("data", "features", configs.task, configs.fv), configs.max_pos_len
    )
    # If video agnostic, randomize the video features.
    if configs.video_agnostic:
        visual_features = {
            key: np.random.rand(*val.shape) for key, val in visual_features.items()
        }
    train_loader = get_train_loader(
        dataset=dataset["train_set"], video_features=visual_features, configs=configs
    )
    val_loader = (
        None
        if dataset["val_set"] is None
        else get_test_loader(dataset["val_set"], visual_features, configs)
    )
    test_loader = get_test_loader(
        dataset=dataset["test_set"], video_features=visual_features, configs=configs
    )
    configs.num_train_steps = len(train_loader) * configs.epochs
    num_train_batches = len(train_loader)

    # Device configuration
    cuda_str = "cuda" if configs.gpu_idx is None else "cuda:{}".format(configs.gpu_idx)
    device = torch.device(cuda_str if torch.cuda.is_available() else "cpu")
    print(f"Using device={device}")

    # create model dir
    home_dir = os.path.join(
        configs.model_dir,
        "_".join(
            [
                configs.model_name,
                configs.task,
                configs.fv,
                str(configs.max_pos_len),
                configs.predictor,
            ]
        ),
    )
    if configs.suffix is not None:
        home_dir = home_dir + "_" + configs.suffix
    model_dir = os.path.join(home_dir, "model")

    writer = None
    if configs.log_to_tensorboard is not None:
        log_dir = os.path.join(configs.tb_log_dir, configs.log_to_tensorboard)
        os.makedirs(log_dir, exist_ok=True)
        print(f"Writing to tensorboard: {log_dir}")
        writer = SummaryWriter(log_dir=log_dir)

    # train and test
    if configs.mode.lower() == "train":
        if not os.path.exists(model_dir):
            os.makedirs(model_dir)
        eval_period = num_train_batches // 2
        save_json(
            vars(configs),
            os.path.join(model_dir, "configs.json"),
            sort_keys=True,
            save_pretty=True,
        )
        # build model
        model = VSLNet(
            configs=configs, word_vectors=dataset.get("word_vector", None)
        ).to(device)

        #3 configurations: 
        #1. STANDARD TRAINING: pretrain == 'no'(Default) and resume_from_checkpoint == None (Default)
        #2. PRE-TRAINING: pretrain == 'yes' and resume_from_checkpoint == None (Default)
        #3. FINE-TUNING: pretrain == 'no' (Default) and resume_from_checkpoint == Path of last pre-training checkpoint
        #to handle fine-tuning
        is_special_fine_tuning = (
          configs.resume_from_checkpoint 
          and os.path.exists(configs.resume_from_checkpoint) 
          and configs.pretrain.lower() == 'no'
        )

        #1. Load the checkpoint for fine-tuning
        if configs.resume_from_checkpoint and os.path.exists(configs.resume_from_checkpoint):
          print(f"Loading checkpoint for fine-tuning from: {configs.resume_from_checkpoint}", flush=True)
          try:
            model.load_state_dict(torch.load(configs.resume_from_checkpoint, map_location=device),strict=True)
            print("Checkpoint successfully loaded", flush=True)

          except Exception as e:
            print(f"ERROR during checkpoint loading: {e}", flush=True)

        # 2. Conditional unfreezing of BERT
        if is_special_fine_tuning:
          # We are in configuration 3. --> Fine-tuning
          print("SPECIAL FINE-TUNING MODE: Unfreezing BERT parameters.", flush=True)
          for param in model.embedding_net.embedder.parameters():
            param.requires_grad = True
        else:
          # We are in configuration 1. or 2. --> Standard training or Pre-training
          # BERT remains frozen as default in layers.py
          print("STANDARD/PRE-TRAINING MODE: BERT remains frozen.", flush=True)
        
        #3. Optimizer configuration
        if is_special_fine_tuning:
          # : Optimizer with different learning rates
          print("Setting up optimizer with differential learning rates for fine-tuning...", flush=True)
          no_decay = ["bias", "layer_norm", "LayerNorm"]
    
          # Separe BERT parameters from the others
          bert_param_ids = {id(p) for p in model.embedding_net.parameters()}
          other_params = [p for p in model.parameters() if id(p) not in bert_param_ids]
    
          optimizer_grouped_parameters = [
          {'params': [p for n, p in model.embedding_net.named_parameters() if not any(nd in n for nd in no_decay)], 'lr': configs.init_lr * 0.1, 'weight_decay': 0.01},
          {'params': [p for n, p in model.embedding_net.named_parameters() if any(nd in n for nd in no_decay)], 'lr': configs.init_lr * 0.1, 'weight_decay': 0.0},
          {'params': other_params, 'lr': configs.init_lr, 'weight_decay': 0.01} # default lr for others
          ]
          optimizer = AdamW(optimizer_grouped_parameters, lr=configs.init_lr)
        else:
          # Cases 1 and 2: Optimizer standard
          print("Setting up standard optimizer.", flush=True)
          optimizer, _ = build_optimizer_and_scheduler(model, configs=configs)

        # 4. Scheduler creation (common to all configurations 1,2,3)
        scheduler = get_linear_schedule_with_warmup(
          optimizer,
          num_warmup_steps=int(configs.num_train_steps * configs.warmup_proportion),
          num_training_steps=configs.num_train_steps,
        )

        # start training
        best_metric = -1.0
        score_writer = open(
            os.path.join(model_dir, "eval_results.txt"), mode="w", encoding="utf-8"
        )
        print("start training...", flush=True)
        global_step = 0
        for epoch in range(configs.epochs):
            model.train()
            for data in tqdm(
                train_loader,
                total=num_train_batches,
                desc="Epoch %3d / %3d" % (epoch + 1, configs.epochs),
            ):
                global_step += 1
                (
                    _,
                    vfeats,
                    vfeat_lens,
                    word_ids,
                    char_ids,
                    s_labels,
                    e_labels,
                    h_labels,
                ) = data
                # prepare features
                vfeats, vfeat_lens = vfeats.to(device), vfeat_lens.to(device)
                s_labels, e_labels, h_labels = (
                    s_labels.to(device),
                    e_labels.to(device),
                    h_labels.to(device),
                )
                if configs.predictor == "bert":
                    word_ids = {key: val.to(device) for key, val in word_ids.items()}
                    # generate mask
                    query_mask = (
                        (
                            torch.zeros_like(word_ids["input_ids"])
                            != word_ids["input_ids"]
                        )
                        .float()
                        .to(device)
                    )
                else:
                    word_ids, char_ids = word_ids.to(device), char_ids.to(device)
                    # generate mask
                    query_mask = (
                        (torch.zeros_like(word_ids) != word_ids).float().to(device)
                    )
                # generate mask
                video_mask = convert_length_to_mask(vfeat_lens).to(device)
                # compute logits
                h_score, start_logits, end_logits = model(
                    word_ids, char_ids, vfeats, video_mask, query_mask
                )
                # compute loss
                loc_loss = model.compute_loss(
                    start_logits, end_logits, s_labels, e_labels
                )
                #total loss if we are using VSLbase
                total_loss=loc_loss
                #if we are using VSLnet we have to consider also QGH loss
                if configs.model_type.lower() == 'vslnet':
                  highlight_loss = model.compute_highlight_loss(h_score, h_labels, video_mask)
                  total_loss += configs.highlight_lambda * highlight_loss
                # compute and apply gradients
                optimizer.zero_grad()
                total_loss.backward()
  
                nn.utils.clip_grad_norm_(
                    model.parameters(), configs.clip_norm
                )  # clip gradient
                optimizer.step()
                scheduler.step()
                if writer is not None and global_step % configs.tb_log_freq == 0:
                    writer.add_scalar("Loss/Total", total_loss.detach().cpu().item(), global_step)
                    writer.add_scalar("Loss/Loc", loc_loss.detach().cpu().item(), global_step)
                    if configs.model_type.lower() == 'vslnet':
                      writer.add_scalar("Loss/Highlight", highlight_loss.detach().cpu().item(), global_step)
                      writer.add_scalar("Loss/Highlight (*lambda)", (configs.highlight_lambda * highlight_loss.detach().cpu()).item(), global_step)
                    writer.add_scalar("LR", optimizer.param_groups[0]["lr"], global_step)

                # evaluate
                if (
                    global_step % eval_period == 0
                    or global_step % num_train_batches == 0
                ):
                    model.eval()
                    print(
                        f"\nEpoch: {epoch + 1:2d} | Step: {global_step:5d}", flush=True
                    )
                    result_save_path = os.path.join(
                        model_dir,
                        f"{configs.model_name}_{epoch}_{global_step}_preds.json",
                    )
                    # Evaluate on val, keep the top 3 checkpoints.
                    results, mIoU, (score_str, score_dict) = eval_test(
                        model=model,
                        data_loader=val_loader,
                        device=device,
                        mode="val",
                        epoch=epoch + 1,
                        global_step=global_step,
                        gt_json_path=configs.eval_gt_json,
                        result_save_path=result_save_path,
                    )
                    print(score_str, flush=True)
                    if writer is not None:
                        for name, value in score_dict.items():
                            kk = name.replace("\n", " ")
                            writer.add_scalar(f"Val/{kk}", value, global_step)

                    score_writer.write(score_str)
                    score_writer.flush()
                    
                    # Recall@1, 0.3 IoU overlap --> best metric.
                    #Save only if we are doing training (no for pre-training)
                    if configs.pretrain.lower() == 'no' and results[0][0] >= best_metric:
                        best_metric = results[0][0]
                        torch.save(
                            model.state_dict(),
                            os.path.join(
                                model_dir,
                                "{}_{}.t7".format(configs.model_name, global_step),
                            ),
                        )
                        # only keep the top-3 model checkpoints
                        filter_checkpoints(model_dir, suffix="t7", max_to_keep=3)
                    model.train()
        #if we are in pre-training phase sve only the last checkpoint
        if configs.pretrain.lower() == 'yes':
          print("\nPre-training finished. Saving the final checkpoint...", flush=True)
          torch.save(
            model.state_dict(),
            os.path.join(
              model_dir,
              "{}_{}.t7".format(configs.model_name, global_step)
            ),
          )
   
        score_writer.close()

    elif configs.mode.lower() == "test":
        if not os.path.exists(model_dir):
            raise ValueError("No pre-trained weights exist")
        # load previous configs
        pre_configs = load_json(os.path.join(model_dir, "configs.json"))
        parser.set_defaults(**pre_configs)
        configs = parser.parse_args()
        # build model
        model = VSLNet(
            configs=configs, word_vectors=dataset.get("word_vector", None)
        ).to(device)

        # get last checkpoint file
        filename = get_last_checkpoint(model_dir, suffix="t7")
        model.load_state_dict(torch.load(filename))
        model.eval()
        result_save_path = filename.replace(".t7", "_test_result.json")
        results, mIoU, score_str = eval_test(
            model=model,
            data_loader=test_loader,
            device=device,
            mode="test",
            result_save_path=result_save_path,
        )
        print(score_str, flush=True)


def create_executor(configs):
    executor = submitit.AutoExecutor(folder=configs.slurm_log_folder)

    executor.update_parameters(
        timeout_min=configs.slurm_timeout_min,
        constraint=configs.slurm_constraint,
        slurm_partition=configs.slurm_partition,
        gpus_per_node=configs.slurm_gpus,
        cpus_per_task=configs.slurm_cpus,
    )
    return executor


if __name__ == "__main__":
    configs, parser = options.read_command_line()
    if not configs.slurm:
        main(configs, parser)
    else:
        executor = create_executor(configs)

        job = executor.submit(main, configs, parser)
        print("job=", job.job_id)

        # wait for it
        if configs.slurm_wait:
            job.result()
