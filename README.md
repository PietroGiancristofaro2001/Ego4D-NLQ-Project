# Machine Learning Project: Natural Language Queries in Egocentric Videos
A brief 1-2 sentence description of the project's goal and the implemented extension (e.g., Data Augmentation using LLMs to improve temporal video grounding).
## Table of Contents
- [Repository Structure](#repository-structure)
- [Setup Instructions](#setup-instructions)
- [Usage](#usage)
- [Results](#results)
- [References](#references)
## Repository Structure
- **/VSLNet_Code**: Contains the source code for the VSLNet model.
- **/notebooks**: Contains the Jupyter notebooks for analysis and implementation.
- **/scripts**: Contains utility scripts, such as the data downloader.
## Setup Instructions
1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/PietroGiancristofaro2001/Ego4D-NLQ-Project.git](https://github.com/PietroGiancristofaro2001/Ego4D-NLQ-Project.git)
    cd Ego4D-NLQ-Project
    ```
2.  **Install Dependencies:**
    ```bash
    pip install -r VSLNet_Code/requirements.txt
    ```
3.  **Download Data:**
    ```bash
    bash scripts/download_data.sh
    ```
## Usage
The notebooks in the `/notebooks` directory are numbered to indicate the recommended execution order:
1.  `00_EDA_and_Setup.ipynb`
2.  `01_Data_Augmentation_with_LLM.ipynb`
3.  `02_Training_and_Evaluation.ipynb`
4.  `03_Results_Analysis.ipynb`
*Note: `_LEGACY_monolithic_notebook.ipynb` is kept as an archive of the initial development.*
## Results
[INSERT FINAL RESULTS TABLE HERE]
## References
[INSERT RELEVANT LINKS HERE]
