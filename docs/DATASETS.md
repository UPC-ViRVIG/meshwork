# Datasets

Sources, licenses and downloads for the paper's datasets. Processing steps are in [REPRODUCTION.md](REPRODUCTION.md).

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
| Images | 81 photographs (Meizu M1 Note) |
| Subject | Decorative flowerpot standing on a table, with a printed scale bar in the scene |
| Author | Natowi |
| Used for | Supporting-plane detection and background removal (Example 2) |

```bash
git clone https://github.com/natowi/dataset_flowerpot.git
```
The `full_dataset/` directory contains the 81 images used in the paper.

**Attribution**: The dataset_flowerpot by Natowi, licensed under CC-BY-SA 4.0. This dataset uses the "Scale for Small-Object Photogrammetry" by Samantha Porter.

## Limestone capital (architectural element)

| Field | Value |
|-------|-------|
| Source | British Museum Digital Humanities |
| URL | https://github.com/BritishMuseumDH/architecturalElement |
| DOI | https://doi.org/10.5281/zenodo.885542 |
| License | CC-BY-NC-SA (Creative Commons Attribution-NonCommercial-ShareAlike) |
| Images | 68 portrait photographs (Sony ILCE-6000, 16 mm) in `images/`, with EXIF rotation tags |
| Masks | Hand-drawn object masks for 58 photographs in `masks/` |
| Subject | Limestone capital, 54 cm high, on a plinth in a gallery corner |
| Author | Daniel Pett, British Museum |
| Used for | Plane detection with a support smaller than the object (Example 4) |

```bash
git clone https://github.com/BritishMuseumDH/architecturalElement.git
```
Masks use the photographs' raw pixel orientation. Pass `--mask-transpose ROTATE_270` to `scripts/eval/object_loss_from_photomasks.py` to match the upright reconstruction images.

**Attribution**: Photographs and models by Daniel Pett, Digital Humanities Lead, British Museum. Copyright Trustees of the British Museum.

## Socketed axe (Arreton Down)

| Field | Value |
|-------|-------|
| Source | MicroPasts crowdsourcing platform |
| URL | https://github.com/MicroPasts/socketed-axe-version2 |
| License | CC-BY |
| Images | 54 photographs in `photos/` (`IMG_8835`-`IMG_8888`), from one capture session |
| Masks | Crowd-sourced masks in `masks/` |
| Subject | Late Bronze / Early Iron Age socketed axe from Arreton Down, Isle of Wight, with its blade wedged into the socket |
| Reference data | `models/`: textured meshes (100k and 300k faces) and a dense point cloud; `other/`: camera positions and alignment markers |
| Used for | Registration and merging (Example 3) |

```bash
git clone https://github.com/MicroPasts/socketed-axe-version2.git
```

The paper uses subsets A (`IMG_8835`-`IMG_8860`, 26 images) and B (`IMG_8861`-`IMG_8888`, 28 images). The PhotoScan Pro 1.1.6 reference model uses the same photographs: `scripts/eval/compare_reference.py` measures agreement between reconstructions, not absolute geometric accuracy.

**Attribution**: Access and photography: Andy Bevan, Chiara Bonacchi, Adi Keinan-Schoonbaert, Dan Pett, Neil Wilkin. Model build: Hugh Fiske. Photo masks: MicroPasts contributors (see the dataset README).
