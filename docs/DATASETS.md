# Datasets

Source information, licenses and download instructions for the datasets used in the MeshWork paper.

## Alexander the Great

| Field | Value |
|-------|-------|
| Source | British Museum Digital Humanities |
| URL | https://github.com/BritishMuseumDH/alexanderTheGreat |
| License | CC-BY-NC-SA (Creative Commons Attribution-NonCommercial-ShareAlike) |
| Images | 57 photographs (Sony A6000), controlled museum lighting |
| Subject | Marble portrait head, British Museum collection |
| Author | Daniel Pett, British Museum |
| Used for | Baseline reconstruction quality (Example 1) |

```bash
git clone https://github.com/BritishMuseumDH/alexanderTheGreat.git
```
The photographs are in the `images/` directory.

**Attribution**: Photographs and models by Daniel Pett, Digital Humanities Lead, British Museum. Copyright Trustees of the British Museum.

## Flowerpot

| Field | Value |
|-------|-------|
| Source | Natowi photogrammetry datasets |
| URL | https://github.com/natowi/dataset_flowerpot |
| License | CC-BY-SA 4.0 (Creative Commons Attribution-ShareAlike 4.0 International) |
| Images | 245 photographs (Meizu M1 Note); the paper uses a subset of 81 |
| Subject | Decorative flowerpot standing on a table, with a printed scale bar in the scene |
| Author | Natowi |
| Used for | Supporting-plane detection and background removal (Example 2) |

```bash
git clone https://github.com/natowi/dataset_flowerpot.git
```
The `full_dataset/` directory contains all 245 images.

**Attribution**: The dataset_flowerpot by Natowi, licensed under CC-BY-SA 4.0. This dataset uses the "Scale for Small-Object Photogrammetry" by Samantha Porter.

## Socketed axe (Arreton Down)

| Field | Value |
|-------|-------|
| Source | MicroPasts crowdsourcing platform |
| URL | https://github.com/MicroPasts/socketed-axe-version2 |
| License | CC-BY |
| Images | 54 photographs in `photos/`, with crowd-sourced masks in `masks/` |
| Subject | Late Bronze / Early Iron Age socketed axe head with the blade wedged into the socket, found on the Isle of Wight |
| Reference data | `models/`: textured meshes (100k and 300k faces) and the dense point cloud produced with PhotoScan Pro 1.1.6; `other/`: camera positions and alignment markers |
| Used for | Multi-scan registration, merging and end-to-end assembly (Example 3); the PhotoScan model serves as an independent reference for `scripts/eval/compare_reference.py` |

```bash
git clone https://github.com/MicroPasts/socketed-axe-version2.git
```

**Attribution**: Access and photography: Andy Bevan, Chiara Bonacchi, Adi Keinan-Schoonbaert, Dan Pett, Neil Wilkin. Model build: Hugh Fiske. Photo masks: MicroPasts contributors (see the dataset README).
