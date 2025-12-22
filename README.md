# PyPI Proxy Server with Dummy Packages

- A smart PyPI proxy server that intercepts package requests and serves tiny dummy packages for large ML libraries (like PyTorch, TensorFlow) while forwarding all other packages to the official PyPI repository.

- Created to solve the problem of installing ML-dependent applications in resource-constrained environments without requiring multi-gigabyte downloads.

- Make Open-webui light-weight!


## 🎯 Purpose

Install Python applications that depend on massive ML libraries **without actually downloading gigabytes of data**. Perfect for:

- **Testing deployments** without full ML stack
- **CI/CD pipelines** where ML features aren't needed
- **Development environments** with limited disk space
- **Containers** that don't need GPU capabilities

## ⚡ Quick Start

### 1. Install Dependencies

```bash
pip install packaging
```

### 2. Run the Proxy Server

```bash
python3 pypi_proxy.py
```

The server will start on `http://localhost:8080`

### 3. Install Packages Through the Proxy

```bash
# Install open-webui with dummy torch (saves ~2GB)
uv pip install --index-url http://localhost:8080/simple/ open-webui

# Or with regular pip
pip install --index-url http://localhost:8080/simple/ open-webui
```

## 📦 Install Open-webui

### Install Open-webui
```bash
# Clear the virtual environment
rm -rf .venv

# Create fresh virtual environment
uv venv

# Activate it
source .venv/bin/activate

# Install open-webui using the proxy (this will get dummy torch automatically)
uv pip install --index-url http://localhost:8080/simple/ open-webui

uv pip install 'langchain-core>=0.3.0,<0.3.30

# diable torch utils
uv pip uninstall torch
```

### Start server

```bash

source .venv/bin/activate
export DATA_DIR=$(pwd)/data/
open-webui serve --port 38030 --host 0.0.0.0
```


## 🔧 Configuration

Edit the `DUMMY_PACKAGES` dictionary in `pypi_proxy.py`:

```python
DUMMY_PACKAGES = {
    'torch': 'auto',           # Auto-detect compatible version
    'torchvision': 'auto',
    'torchaudio': 'auto',
    'tensorflow': '2.15.0',    # Or specify exact version
}
```

- **`'auto'`**: Automatically fetches the latest compatible version from PyPI
- **`'2.15.0'`**: Uses the specified version number

## 📋 Features

### Smart Version Detection

The proxy can automatically detect compatible versions:

```bash
# Analyze what versions a package needs
python3 pypi_proxy.py --analyze open-webui
```

Output:
```
🔍 Analyzing dependencies for: open-webui

Latest version: 0.6.41

Dependencies:
------------------------------------------------------------
  📦 torch                        >=1.11.0             → 2.1.2
  📦 torchvision                  >=0.12.0             → 0.16.0
```

### Real-time Logging

The server shows what's happening:

```
📦 GET  [DUMMY] torch
  🤖 Auto-detected version: 2.9.1
  ✓ Served wheel for torch v2.9.1 (2048 bytes)

🌐 GET  [PROXY] requests
🌐 GET  [PROXY] fastapi
```

- 📦 **DUMMY** = Serving tiny stub package
- 🌐 **PROXY** = Forwarding to real PyPI

## 🎛️ Advanced Usage

### Multiple Package Managers

Works with pip, uv, poetry, etc:

```bash
# uv (fastest)
uv pip install --index-url http://localhost:8080/simple/ package-name

# pip
pip install --index-url http://localhost:8080/simple/ package-name

# poetry
poetry source add pypi-proxy http://localhost:8080/simple/ --priority=primary
poetry install
```

### Custom Port

```python
# Edit pypi_proxy.py
if __name__ == '__main__':
    run_server(port=9000)  # Use port 9000 instead
```

### Permanent Configuration

Set as default index URL:

```bash
# In pip.conf or ~/.config/pip/pip.conf
[global]
index-url = http://localhost:8080/simple/
```

## 💾 Space Savings

Real-world example installing `open-webui`:

| Package | Real Size | Dummy Size | Savings |
|---------|-----------|------------|---------|
| torch | 2.3 GB | 2 KB | ~2.3 GB |
| torchvision | 800 MB | 2 KB | ~800 MB |
| torchaudio | 400 MB | 2 KB | ~400 MB |
| **Total** | **3.5 GB** | **~6 KB** | **~3.5 GB** |

## ⚠️ Important Notes

### When Dummy Packages Work

✅ **Perfect for:**
- Applications with optional ML features
- Testing API integrations
- Development without GPU
- Dependency resolution testing

### When They Don't Work

❌ **Won't work if:**
- Application actually calls ML functions at runtime
- Code imports specific torch modules (`torch.nn`, `torch.optim`)
- Application validates package integrity

### Runtime Behavior

The dummy packages:
- ✅ Satisfy pip dependency resolution
- ✅ Can be imported: `import torch`
- ✅ Have `__version__` attribute
- ❌ Don't have actual ML functionality
- ❌ Will raise errors if ML methods are called

### Proxy Not Responding

Check if the server is running:

```bash
curl http://localhost:8080/simple/
```

## 🔍 How It Works

1. **Client requests** a package (e.g., `torch`)
2. **Proxy checks** if it's in `DUMMY_PACKAGES`
3. **If yes**: Creates a minimal wheel file on-the-fly with just `__init__.py`
4. **If no**: Forwards request to `https://pypi.org`
5. **Client installs** the package normally

### Dummy Package Structure

```
torch-2.1.0-py3-none-any.whl
├── torch/
│   └── __init__.py          # Contains: __version__ = "2.1.0"
└── torch-2.1.0.dist-info/
    ├── METADATA
    ├── WHEEL
    ├── RECORD
    └── top_level.txt
```

Total size: ~2 KB vs ~2.3 GB for real torch!


**Potential savings**: 600-700 MB additional

## 🤝 Contributing

To add more dummy packages:

1. Edit `DUMMY_PACKAGES` in `pypi_proxy.py`
2. Run the analyzer to find compatible versions:
   ```bash
   python3 pypi_proxy.py --analyze your-package
   ```
3. Test the installation

## 📄 License

MIT License - Feel free to use and modify!

---

**Pro Tip**: Use this with Docker multi-stage builds to create tiny production images! 🐳
