# AMD GPU setup (Radeon RX 9000, Windows)

How to train the CNN on a Radeon RX 9000 series card under Windows 11 with AMD's ROCm build of PyTorch. The training code needs no changes: ROCm builds expose the GPU as PyTorch's `cuda` device, and `gfc-train-cnn` picks `cuda` automatically ([CNN trainer, Hardware](roadmap/tools/cnn-trainer.md#hardware), D23).

Training support on Windows is recent. AMD's ROCm 7.2.1 pages listed "No ML training support" for Windows; the ROCm 10.1.0 pages no longer list that limitation, but they do not state training support explicitly either. Section 3 is therefore the real test, and nothing should depend on the GPU until it passes.

The CPU environment stays the default and the fallback. The GPU environment is a second virtual environment next to it, so a broken GPU install never blocks work.

**Related:** [training pipeline](training-pipeline.md) · [CNN trainer](roadmap/tools/cnn-trainer.md) · [design decisions](design-decisions.md) (D23)

---

## 1. Requirements

Versions are those of ROCm 10.1.0, the current release when this page was written. AMD's [compatibility matrix](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html) is the authority when it disagrees with this table.

| | Requirement | How to check |
|---|---|---|
| GPU | RX 9070 XT, 9070, 9070 GRE (`gfx1201`); RX 9060 XT, 9060, 9050 (`gfx1200`) | Device Manager → Display adapters |
| OS | Windows 11 25H2 | `winver` |
| Driver | AMD Software: Adrenalin Edition, 26.10 branch (ROCm 10.1.0 lists driver 26.10.41.05) | AMD Software → System, or the PowerShell check below |
| Python | 3.12 (AMD supports 3.11–3.14; the project uses 3.12) | `py -0p` |
| Smart App Control | Off (AMD: can interfere with ROCm) | Windows Security → App & browser control |
| Application Guard (WDAG) | Off | Windows Features |
| Old HIP SDK | Not installed (AMD: remove any HIP SDK for Windows and conflicting AMD graphics software) | Installed apps |
| Disk | About 5 GB for the environment | |

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

`.venv-rocm/` is git-ignored.

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
python -c "import torch, torchvision; print(torch.__version__, torchvision.__version__)"
```

The second line must still print `+rocm10.1.0` versions. The `train` group does not pin `torch`, so pip keeps the ROCm build that is already installed. If a plain `torch` from PyPI ever replaces it, repeat 2.2.

---

## 3. Verify

```powershell
python -c "import torch; print(torch.cuda.is_available(), torch.version.hip, torch.cuda.get_device_name(0))"
```

Expected: `True`, a HIP version, and the card name.

Then a training-shaped check (convolution, backward pass, optimiser step) on the GPU:

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

On the GPU the model step becomes faster than augmentation in the main process. Set `num_workers` to 2–4 with `cache: "none"` in `config/train_cnn.json` when the GPU sits idle between batches ([loader working defaults](roadmap/tools/dataset-loader.md#working-defaults-d35)).

Close games and other GPU-heavy programs while training; they share the same 16 GB of video memory.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `torch.cuda.is_available()` is `False` | Driver outside the version ROCm expects: install the Adrenalin driver linked from AMD's ROCm release notes for this ROCm version, reboot, check again. Confirm Smart App Control and WDAG are off and no old HIP SDK is installed |
| Import error about a missing `.dll` | Install the Microsoft Visual C++ 2015–2022 Redistributable (x64) |
| GPU reset or crash during training | AMD's documented workaround for RX 9070 series training: `$env:TORCH_BLAS_PREFER_HIPBLASLT = "0"` before training |
| First epoch much slower than the rest | Kernel selection on first use; later epochs and runs are faster |
| Versions without `+rocm` after installing the project | A PyPI `torch` replaced the ROCm one; repeat 2.2 |
| Anything else unresolved within an hour | Train on CPU and come back later; nothing in the pipeline depends on the GPU |

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
