# AMD GPU setup (Radeon RX 9000, Windows)

How to train the CNN on a Radeon RX 9000 series card under Windows 11 with AMD's ROCm build of PyTorch. The training code needs no changes: ROCm builds expose the GPU as PyTorch's `cuda` device, and `gfc-train-cnn` picks `cuda` automatically ([CNN trainer, Hardware](roadmap/tools/cnn-trainer.md#hardware), D23).

Training support on Windows is recent. AMD's ROCm 7.2.1 pages listed "No ML training support" for Windows; the ROCm 10.1.0 pages no longer list that limitation, but they do not state training support explicitly either. Section 3 is therefore the real test, and nothing should depend on the GPU until it passes (it passed on 2026-11-17, see below).

**Tested 2026-11-17** on an RX 9070 XT (`gfx1201`), Adrenalin 26.10.1, Windows 11 25H2, Python 3.12.7, `torch 2.14.0+rocm10.1.0`: the install, the checks in section 3, an overfit test, a continuous training run of 11 minutes and a benchmark all passed. Results and timings are in [CNN trainer, Training time](roadmap/tools/cnn-trainer.md#training-time).

This is the project's primary training route (D23); the CPU is the fallback. The GPU environment is a second virtual environment next to the normal one, so a broken GPU install never blocks work: train with `--device cpu`, or from the normal environment, until it is fixed.

**Related:** [training pipeline](training-pipeline.md) · [CNN trainer](roadmap/tools/cnn-trainer.md) · [design decisions](design-decisions.md) (D23)

---

## 1. Requirements

Versions are those of ROCm 10.1.0, the current release when this page was written. AMD's [compatibility matrix](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html) is the authority when it disagrees with this table.

| | Requirement | How to check |
|---|---|---|
| GPU | RX 9070 XT, 9070, 9070 GRE (`gfx1201`); RX 9060 XT, 9060, 9050 (`gfx1200`) | Device Manager → Display adapters |
| OS | Windows 11 25H2 | `winver` |
| Driver | AMD Software: Adrenalin Edition, 26.10 branch (ROCm 10.1.0 lists driver 26.10.41.05; **26.10.1 was tested and works**, with the harmless MIOpen warning in section 5) | AMD Software → System, or the PowerShell check below |
| Python | 3.12 (AMD supports 3.11–3.14; the project uses 3.12) | `py -0p` |
| Smart App Control | Off (AMD: can interfere with ROCm) | Windows Security → App & browser control |
| Application Guard (WDAG) | Off | Windows Features |
| Old HIP SDK | Not installed (AMD: remove any HIP SDK for Windows and conflicting AMD graphics software) | Installed apps |
| Disk | About 4.5 GB for the environment (4.2 GB measured) | |

The card name differs only in the wheel variant: `device-gfx1201` for the RX 9070 family, `device-gfx1200` for the RX 9060 / 9050 family. Everything else on this page is the same for the whole series.

PowerShell check of the driver, Windows version and Smart App Control state (`VerifiedAndReputablePolicyState`: `0` off, `1` on, `2` evaluation):

```powershell
Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}' |
  ForEach-Object { Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue } |
  Where-Object DriverDesc -like '*Radeon*' | Select-Object DriverDesc, RadeonSoftwareVersion
(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').DisplayVersion
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' | Select-Object VerifiedAndReputablePolicyState
```

Turning Smart App Control off cannot be undone from Settings on most Windows 11 builds; it comes back only with a Windows reset. Decide on that before changing it.

---

## 2. Install

From the repo root, in PowerShell.

### 2.1 Environment

```powershell
py -3.12 -m venv .venv-rocm
.\.venv-rocm\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

`.venv-rocm/` is git-ignored. If PowerShell refuses to run `Activate.ps1` (script execution policy), skip activation and call `.\.venv-rocm\Scripts\python.exe` directly in every later command.

### 2.2 PyTorch for ROCm

RX 9070 family:

```powershell
python -m pip install --index-url https://stable.repo.amd.com/rocm/whl-next/ `
  "torch[device-gfx1201]==2.14.0+rocm10.1.0" `
  "torchvision[device-gfx1201]==0.29.0a0+rocm10.1.0"
```

RX 9060 / 9050 family: the same command with `device-gfx1200`.

The `device-…` extra pulls the GPU kernels for that architecture only (`rocm-sdk-device-gfx1201`), which keeps the download much smaller than `device-all`. `torchaudio` is not used by this project.

### 2.3 Project

```powershell
python -m pip install -e ".[dev,train]"
python -c "import torch, torchvision, matplotlib; print(torch.__version__, torchvision.__version__, matplotlib.__version__)"
```

The `train` optional group (`numpy`, `torch`, `torchvision`, `scikit-learn`, `matplotlib`) is what evaluation figures and the baseline need at the end of a GPU training run. It must not pin `torch`, so pip keeps the ROCm build from 2.2. The check line must still print `+rocm10.1.0` for torch and torchvision (tested: `2.14.0+rocm10.1.0 0.29.0a0+rocm10.1.0`) plus a matplotlib version. If a plain `torch` from PyPI ever replaces the ROCm build, repeat 2.2.

If the environment already has the ROCm wheels and only figure or baseline packages are missing, install them without touching torch:

```powershell
python -m pip install matplotlib scikit-learn
```

---

## 3. Verify

```powershell
python -c "import torch; print(torch.cuda.is_available(), torch.version.hip, torch.cuda.get_device_name(0))"
```

Expected: `True`, a HIP version, and the card name. Tested output: `True 7.16.26385 AMD Radeon RX 9070 XT`. The first GPU call prints one `MIOpen: Warning [ParseAndLoadDb] File is unreadable: ...gfx120140.HIP.fdb.txt` line; it is harmless (section 5).

Then a training-shaped check (convolution, backward pass, optimiser step) on the GPU. Tested: prints `ok 0.0765 s/step`.

```powershell
python -c "import torch,torch.nn as nn,time; d='cuda'; m=nn.Sequential(nn.Conv2d(3,32,3,padding=1),nn.BatchNorm2d(32),nn.ReLU(),nn.MaxPool2d(2),nn.Flatten(),nn.Linear(32*72*128,6)).to(d); o=torch.optim.Adam(m.parameters()); x=torch.randn(64,3,144,256,device=d); y=torch.randint(0,6,(64,),device=d); [(o.zero_grad(),nn.functional.cross_entropy(m(x),y).backward(),o.step()) for _ in range(3)]; torch.cuda.synchronize(); t=time.perf_counter(); [(o.zero_grad(),nn.functional.cross_entropy(m(x),y).backward(),o.step()) for _ in range(20)]; torch.cuda.synchronize(); print('ok', round((time.perf_counter()-t)/20,4),'s/step')"
```

Once the trainer exists, the real acceptance check is the same one used for any new device:

```powershell
pytest tests/unit/test_model.py tests/system/test_train.py
gfc-train-cnn --split-dir data/manifests/splits/v1 --epochs 2 --limit 256 --tag gpu-smoke
```

Compare the smoke run's `history.csv` with a CPU smoke run of the same command: losses should be close, not identical (GPU kernels are not bit-identical to CPU). Then record the measured time per epoch in [cnn-trainer.md](roadmap/tools/cnn-trainer.md#training-time).

---

## 4. Use

```powershell
.\.venv-rocm\Scripts\Activate.ps1
gfc-train-cnn --split-dir data/manifests/splits/v1          # device "auto" picks the GPU
gfc-train-cnn --split-dir data/manifests/splits/v1 --device cpu
```

On the GPU the model step (0.08 s per batch of 64) is about 2.5 times faster than augmentation in the main process (about 0.2 s), so with `num_workers` 0 the GPU idles about 70 % of the time. Measured: 2 workers already keep the GPU busy (0.076 s per batch); 4 workers gave no further gain (0.083 s). Each epoch pays about 4 s to start the workers on Windows. Use `num_workers` 2 with `cache: "none"` for the train loader only (the val loader needs no augmentation; give it 0 workers, or each epoch pays the start-up twice), and only from roughly 5,000 train frames upward; below that, 0 workers is faster. Set it in `config/train_cnn.json` ([loader working defaults](roadmap/tools/dataset-loader.md#working-defaults-d35)); the entry point must be under `if __name__ == "__main__":` because Windows starts workers by spawning.

Peak GPU memory for the default model at batch 64 is about 1.9 GB. Close games and other GPU-heavy programs while training; they share the same 16 GB of video memory.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `torch.cuda.is_available()` is `False` | Driver outside the version ROCm expects: install the Adrenalin driver linked from AMD's ROCm release notes for this ROCm version, reboot, check again. Confirm Smart App Control and WDAG are off and no old HIP SDK is installed |
| Import error about a missing `.dll` | Install the Microsoft Visual C++ 2015–2022 Redistributable (x64) |
| `MIOpen: Warning [ParseAndLoadDb] File is unreadable: ...\gfx120140.HIP.fdb.txt` on the first GPU call | Harmless: training, evaluation and the benchmarks all ran correctly with it. The cause was not investigated (the file is a MIOpen tuning database that cannot be read) |
| GPU reset or crash during training | AMD's documented workaround for RX 9070 series training: `$env:TORCH_BLAS_PREFER_HIPBLASLT = "0"` before training. **Not needed in testing**: no crash, reset or NaN in the 11-minute run or anything else, all without the variable |
| First epoch much slower than the rest | Kernel selection on first use: about 20 s extra once per process (measured 29 s against 6.4 s per epoch at 2,065 frames); later epochs are faster |
| Versions without `+rocm` after installing the project | A PyPI `torch` replaced the ROCm one; repeat 2.2 |
| Anything else unresolved within an hour | Fall back to the CPU (`--device cpu`) and come back later; nothing in the pipeline needs the GPU to be correct, only to be fast |

To remove the GPU environment, delete the `.venv-rocm` folder.

---

## 6. Other routes

| Route | When | Note |
|---|---|---|
| CPU (`.venv` or the system Python) | Always available | About 3 min per epoch at 10,000 train frames |
| WSL2 + Ubuntu with ROCm | Native Windows install will not work | Technical preview in ROCm 10.1.0; RX 9070 support on WSL2 not confirmed in AMD's docs at the time of writing |
| Colab GPU | No local GPU route works | Upload `data/frames/` and the split folder as a zip; same command |

---

## 7. Sources

- [ROCm documentation (current release)](https://rocm.docs.amd.com/en/latest/)
- [ROCm compatibility matrix](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html)
- [PyTorch on ROCm: install](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html)
- [ROCm install (Windows section)](https://rocm.docs.amd.com/en/latest/install/rocm.html)
- [ROCm on Radeon and Ryzen, Windows PyTorch (7.2.1 and earlier)](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installryz/windows/install-pytorch.html)
