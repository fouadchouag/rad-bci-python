# Glossary

A reference of BCI, EEG, and RBciAD terminology.

## BCI & Neuroscience

| Term | Definition |
|---|---|
| **BCI** | Brain-Computer Interface. A system that measures brain activity (typically EEG) and translates it into commands for a computer. |
| **EEG** | Electroencephalography. A non-invasive method of recording electrical activity from the scalp using electrodes. |
| **Motor Imagery (MI)** | A BCI paradigm where the user imagines performing a movement (e.g., left hand, right hand, feet) without actually moving. The brain produces detectable patterns. |
| **ERD/ERS** | Event-Related Desynchronization / Synchronization. Changes in EEG power in specific frequency bands during motor imagery. ERD = decrease (active), ERS = increase (idle). |
| **CSP** | Common Spatial Patterns. A spatial filtering technique that finds EEG projections maximizing the variance difference between two classes. |
| **FBCSP** | Filter-Bank Common Spatial Patterns. CSP applied to multiple frequency sub-bands, then selecting the most discriminative features. |
| **TS-FBCSP** | Tangent-Space Filter-Bank CSP. Projects FBCSP features into the tangent space of covariance matrices for improved classification. |
| **Epoch** | A segment of EEG data time-locked to an event (e.g., a cue telling the user to imagine left hand movement). |
| **Trial** | One complete event: cue → imagination → response. Typically 3–7 seconds long. |
| **Channel** | A single EEG electrode/sensor. Common systems use 16, 22, 32, 64, or 128 channels. |
| **Montage** | The spatial arrangement of EEG electrodes on the scalp (e.g., standard 10-20, 10-10 system). |
| **Referencing** | A method of re-referencing EEG signals. Common Average Reference (CAR) subtracts the mean of all channels from each channel. |
| **Artifact** | Unwanted signal contamination from non-brain sources (eye blinks, muscle activity, power line noise, electrode movement). |
| **SSP** | Signal Space Projection. A method for removing artifacts (e.g., eye blinks) by projecting EEG data onto a subspace orthogonal to the artifact. |
| **ICA** | Independent Component Analysis. A blind source separation technique that decomposes EEG into independent components, useful for artifact removal. |

## Signal Processing

| Term | Definition |
|---|---|
| **Bandpass Filter** | A filter that passes frequencies within a range (e.g., 8–30 Hz) and attenuates frequencies outside it. |
| **Notch Filter** | A filter that removes a narrow frequency band (e.g., 50 Hz or 60 Hz power line noise). |
| **Low-pass Filter** | Passes frequencies below a cutoff; removes high-frequency noise. |
| **High-pass Filter** | Passes frequencies above a cutoff; removes slow drift. |
| **SOS** | Second-Order Sections. A numerically stable way to implement IIR filters (used by `scipy.signal`). |
| **Nyquist Frequency** | Half the sampling rate. The maximum frequency that can be represented without aliasing. |
| **Sampling Frequency (sfreq)** | The number of EEG samples recorded per second, in Hz (e.g., 256 Hz, 512 Hz). |

## Machine Learning

| Term | Definition |
|---|---|
| **Feature** | A numerical descriptor extracted from EEG data (e.g., bandpower, CSP weight, covariance element). |
| **Feature Extraction** | The process of converting raw EEG into a compact numerical representation suitable for classification. |
| **Classifier** | An algorithm that maps features to class labels (e.g., "left hand" vs. "right hand"). |
| **LR** | Logistic Regression. A simple, fast linear classifier. |
| **SVM** | Support Vector Machine. A classifier that finds the optimal separating hyperplane. |
| **Random Forest (RF)** | An ensemble classifier using multiple decision trees. |
| **Cross-Validation** | A technique for estimating model performance by splitting data into training and test folds. |
| **Accuracy** | The percentage of correctly classified trials. |
| **Balanced Accuracy** | Average recall across all classes, useful when class sizes are unequal. |
| **Confusion Matrix** | A table showing actual vs. predicted class labels. |
| **Overfitting** | When a model learns noise in the training data instead of generalizable patterns. Cross-validation helps detect it. |

## Riemannian Geometry

| Term | Definition |
|---|---|
| **Covariance Matrix** | A symmetric positive-definite (SPD) matrix summarizing the relationships between EEG channels. |
| **SPD Matrix** | Symmetric Positive-Definite matrix. Covariance matrices are SPD. Riemannian geometry operates on the manifold of SPD matrices. |
| **Riemannian Mean** | The geometric mean of multiple covariance matrices on the SPD manifold. Computed iteratively via gradient descent. |
| **Tangent Space** | A flat (Euclidean) approximation of the SPD manifold at a reference point. Projecting covariance matrices to tangent space enables standard ML classifiers. |
| **Euclidean Alignment (EA)** | A normalization technique that whitens each subject's data using a subject-specific reference matrix, enabling cross-subject generalization. |
| **OAS Shrinkage** | Oracle Approximating Shrinkage. A method for estimating covariance matrices that is robust to limited samples. |
| **Whitening Matrix** | A matrix that normalizes data so its covariance is the identity matrix. Used in Euclidean Alignment. |

## RBciAD Specific

| Term | Definition |
|---|---|
| **Node** | A processing block in the visual editor. Defined by a Python plugin class. |
| **Pin** | An input or output connection point on a node. Each pin has a family (data type). |
| **Family** | The data type of a pin (e.g., `raw`, `segment`, `features`, `cov`, `model`). Connections require matching families. |
| **Cable** | A visual connection between an output pin and an input pin. Data flows through cables. |
| **Workflow** | A complete pipeline graph saved as a JSON file. Contains nodes, positions, connections, and configurations. |
| **Plugin** | A Python class inheriting from `BasePlugin` that defines a node's inputs, outputs, parameters, and behavior. |
| **BehaviorSubject** | An RxPY stream type used by RBciAD to carry data between nodes. |
| **Low-code** | A GUI tool for creating new nodes without writing code. Access via the toolbar. |
| **Polyglot** | RBciAD's ability to mix nodes written in different languages (Python, Rust, C, Node.js). |
| **TTFP** | Time To First Plot. The latency from loading data to seeing the first visual output. Target: <250ms. |
| **FPS** | Frames Per Second. The rendering speed of visual nodes. Target: ≥50 FPS. |
