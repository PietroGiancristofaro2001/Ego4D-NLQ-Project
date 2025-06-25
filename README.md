# Natural Language Queries in Egocentric Videos with VSLNet

## 1. Project Overview

This project explores the task of Natural Language Queries (NLQ) in egocentric videos, where the goal is to identify a specific temporal segment in a video that answers a natural language question.

This repository implements and extends the VSLNet architecture to conduct a series of experiments on the Ego4D NLQ benchmark. The project is structured into three main experimental phases:

1.  **Model and Feature Comparison**: We first determine the best combination of model architecture and visual features. Using BERT as a constant text encoder, we compare the performance of all possible combinations between model types (`vslnet`, `vslbase`) and video features (`omnivore`, `egovlp`). The `--model_type` parameter was used to switch between architectures during these runs.

2.  **Text Encoder Comparison**: Using the best-performing model-feature combination from the previous phase (VSLNet + EgoVLP), we conduct a comparative analysis between two text encoders: **BERT** (the modern baseline for the Ego4D NLQ task) and **GloVe** (the baseline from the original VSLNet paper).

3.  **Data Augmentation, Pre-training, and Fine-tuning**: The main contribution of this project is a novel pipeline to improve performance. We use a Large Language Model (LLM) to generate a new synthetic dataset from the narrations of the entire Ego4D dataset. The workflow is as follows:
    * The model is first **pre-trained** on this large, synthetic dataset (using the `--pretrain=yes` flag).
    * The resulting pre-trained model is then **fine-tuned** on the smaller, official NLQ training dataset. This is achieved by loading the checkpoint from the pre-training phase via the `--resume_from_checkpoint` argument.

To enable this experimental workflow, the original codebase was modified. Key changes were made to `options.py` to add the new configuration flags, and to `main.py` to handle the different training and data-loading logics. The core `VSLNet.py` model was also adapted.


## 2. Repository Structure

This repository is organized into two main parts: the `VSLNet_Code` directory and a `notebooks` directory containing the project's workflow.

```
ego4d-nlq-project/
├── VSLNet_Code/
│   ├── main.py              # Main script for training and evaluation (modified)
│   ├── options.py           # Script defining configuration parameters (modified)
│   ├── requirements.txt     # Project dependencies
│   ├── run_train.sh         # Example bash script for training
│   ├── model/
│   │   ├── VSLNet.py        # VSLNet and VSLBase model definitions (modified)
│   │   └── layers.py        # Custom layers for the architecture
│   └── utils/
│       └── prepare_ego4d_dataset.py
│
└── notebooks/
    ├── 01_Exploratory_Data_Analysis.ipynb
    ├── 02_Training_and_Evaluation.ipynb
    └── 03_Data_Augmentation_with_LLM.ipynb
```


## 3. Getting Started

### 3.1. Prerequisites

* Python 3.8+
* PyTorch
* Transformers
* Other dependencies are listed in `VSLNet_Code/requirements.txt`.

### 3.2. Dataset and Features

To run this project, you need a single `.zip` archive containing all the necessary data. This archive must be structured to include:
* All Ego4D annotations (v1), including `nlq_train.json`, `nlq_val.json`, etc.
* Pre-extracted **Omnivore** and **EgoVLP** visual features.
* The pre-trained GloVe word embedding file (`glove.840B.300d.txt`).

## 4. How to Run the Project

The entire workflow is managed through the **Google Colab notebooks** in the `/notebooks` directory. It is highly recommended to run them in a Colab environment with GPU acceleration enabled.
The notebooks are structured in a simple way, it's only needed to run all cells sequentially.

### 4.1. Notebook 01: Exploratory Data Analysis

This notebook performs a detailed analysis of the Ego4D NLQ dataset. It explores the distribution of query templates, the duration of video clips and answer segments, and the correlation between queries and video scenarios.

### 4.2. Notebook 02: Training and Evaluation

This notebook provides a streamlined workflow to train and evaluate the baseline models (VSLBase/VSLNet) from scratch on the official dataset.

* **Setup**: Configure the experiment by setting the `MODEL_TYPE` (`vslnet` or `vslbase`) and `FEATURE_TYPE` (`omnivore` or `egovlp`).
* **Execution**: Run the cells sequentially to prepare the data and launch the training script.

### 4.3. Notebook 03: Data Augmentation and Fine-Tuning

This notebook implements the main extension of this project: a pre-training/fine-tuning pipeline using LLM-generated data.

1.  **Phase I - Data Augmentation**: The notebook first generates a synthetic dataset. It groups consecutive narrations from `narration.json`, filters them, and uses a `Llama-3-8B-Instruct` model to generate corresponding NLQ-style questions. The process is fault-tolerant and saves progress to Google Drive.
2.  **Phase II - Pre-training**: The model is then pre-trained on this newly created augmented dataset.
3.  **Phase III - Fine-tuning**: Finally, the pre-trained model is fine-tuned on the official `nlq_train.json` dataset.
