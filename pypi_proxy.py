#!/usr/bin/env python3
"""
Smart PyPI Proxy Server that auto-detects required versions.
Usage: python pypi_proxy.py [--analyze package_name]
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import json
import tempfile
import os
import shutil
import re
import sys
import zipfile
import hashlib
import base64
from pathlib import Path
from packaging.specifiers import SpecifierSet
from packaging.version import Version

# IMPORTANT: Only add packages HERE that you want to REPLACE with dummy versions
DUMMY_PACKAGES = {
    'torch': 'auto',
    'torchvision': 'auto',
    'torchaudio': 'auto',
}

PYPI_INDEX = "https://pypi.org"
VERSION_CACHE = {}
METADATA_CACHE = {}


def fetch_package_info(package_name):
    """Fetch package metadata from PyPI."""
    try:
        url = f"{PYPI_INDEX}/pypi/{package_name}/json"
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read())
    except Exception as e:
        print(f"  ✗ Error fetching info for {package_name}: {e}")
        return None


def find_compatible_version(package_name, specifier_str=''):
    """Find a version that satisfies the specifier."""
    cache_key = f"{package_name}:{specifier_str}"
    if cache_key in VERSION_CACHE:
        return VERSION_CACHE[cache_key]
    
    info = fetch_package_info(package_name)
    if not info:
        return '99.0.0'
    
    versions = list(info.get('releases', {}).keys())
    if not versions:
        return '99.0.0'
    
    try:
        parsed_versions = []
        for v in versions:
            try:
                parsed_versions.append(Version(v))
            except:
                pass
        
        if not parsed_versions:
            return '99.0.0'
        
        parsed_versions.sort(reverse=True)
        
        if not specifier_str or specifier_str == '*':
            for v in parsed_versions:
                if not v.is_prerelease:
                    result = str(v)
                    VERSION_CACHE[cache_key] = result
                    return result
            result = str(parsed_versions[0])
            VERSION_CACHE[cache_key] = result
            return result
        
        spec = SpecifierSet(specifier_str)
        for v in parsed_versions:
            if v in spec and not v.is_prerelease:
                result = str(v)
                VERSION_CACHE[cache_key] = result
                return result
        
        for v in parsed_versions:
            if v in spec:
                result = str(v)
                VERSION_CACHE[cache_key] = result
                return result
        
        result = str(parsed_versions[0])
        VERSION_CACHE[cache_key] = result
        return result
        
    except Exception as e:
        print(f"  ✗ Error parsing versions for {package_name}: {e}")
        return '99.0.0'


def get_real_package_metadata(package_name, version=None):
    """Fetch real metadata for a package from PyPI."""
    cache_key = f"meta:{package_name}:{version}"
    if cache_key in METADATA_CACHE:
        return METADATA_CACHE[cache_key]
    
    try:
        if version:
            url = f"{PYPI_INDEX}/pypi/{package_name}/{version}/json"
        else:
            url = f"{PYPI_INDEX}/pypi/{package_name}/json"
        
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read())
        
        info = data.get('info', {})
        result = {
            'name': info.get('name', package_name),
            'version': info.get('version', version or '0.0.0'),
            'summary': info.get('summary', ''),
            'home_page': info.get('home_page', ''),
            'author': info.get('author', ''),
            'author_email': info.get('author_email', ''),
            'license': info.get('license', ''),
            'requires_python': info.get('requires_python', '>=3.8'),
            'requires_dist': info.get('requires_dist', []) or [],
            'classifiers': info.get('classifiers', []) or [],
            'keywords': info.get('keywords', ''),
            'description': info.get('description', ''),
            'description_content_type': info.get('description_content_type', 'text/markdown'),
        }
        
        METADATA_CACHE[cache_key] = result
        return result
        
    except Exception as e:
        print(f"  ⚠ Could not fetch metadata for {package_name}: {e}")
        return None


def generate_metadata_file(package_name, version, include_real_deps=False):
    """
    Generate proper METADATA content compliant with PEP 566/PEP 643.
    This is called during wheel creation to ensure valid metadata.
    """
    # Try to get real metadata from PyPI
    real_meta = get_real_package_metadata(package_name, version)
    
    # Normalize package name (PEP 503: lowercase, hyphens)
    normalized_name = package_name.lower().replace('_', '-')
    
    # Build METADATA content - order matters for some parsers
    lines = []
    
    # Required core metadata (PEP 566)
    lines.append("Metadata-Version: 2.1")
    lines.append(f"Name: {normalized_name}")
    lines.append(f"Version: {version}")
    
    # Optional but recommended fields
    if real_meta:
        if real_meta.get('summary'):
            lines.append(f"Summary: {real_meta['summary']}")
        else:
            lines.append(f"Summary: Dummy stub for {package_name}")
        
        if real_meta.get('home_page'):
            lines.append(f"Home-page: {real_meta['home_page']}")
        
        if real_meta.get('author'):
            lines.append(f"Author: {real_meta['author']}")
        
        if real_meta.get('author_email'):
            lines.append(f"Author-email: {real_meta['author_email']}")
        
        if real_meta.get('license'):
            # Truncate long license text
            license_text = real_meta['license']
            if len(license_text) > 100:
                license_text = license_text[:100].split('\n')[0]
            lines.append(f"License: {license_text}")
        
        if real_meta.get('keywords'):
            lines.append(f"Keywords: {real_meta['keywords']}")
        
        if real_meta.get('requires_python'):
            lines.append(f"Requires-Python: {real_meta['requires_python']}")
        else:
            lines.append("Requires-Python: >=3.8")
        
        # Add classifiers
        for classifier in real_meta.get('classifiers', [])[:20]:  # Limit to 20
            lines.append(f"Classifier: {classifier}")
        
        # Add dependencies (filtered)
        if include_real_deps:
            for dep in real_meta.get('requires_dist', []):
                # Extract base package name
                dep_name = re.split(r'[\s\[\]<>=!;]', dep)[0].lower().replace('_', '-')
                # Skip if it's a dummy package (we don't want real deps on dummy packages)
                if dep_name not in DUMMY_PACKAGES:
                    lines.append(f"Requires-Dist: {dep}")
    else:
        # Fallback when can't fetch from PyPI
        lines.append(f"Summary: Dummy stub package for {package_name}")
        lines.append("Home-page: https://pypi.org/project/{}/".format(package_name))
        lines.append("Author: PyPI Proxy")
        lines.append("Author-email: proxy@localhost")
        lines.append("License: MIT")
        lines.append("Requires-Python: >=3.8")
        lines.append("Classifier: Development Status :: 4 - Beta")
        lines.append("Classifier: Intended Audience :: Developers")
        lines.append("Classifier: Programming Language :: Python :: 3")
    
    # Description content type
    lines.append("Description-Content-Type: text/markdown")
    
    # Blank line separates headers from body (REQUIRED)
    lines.append("")
    
    # Description body
    lines.append(f"# {package_name}")
    lines.append("")
    lines.append(f"**This is a dummy stub package for `{package_name}` version {version}.**")
    lines.append("")
    lines.append("Generated by PyPI Proxy to satisfy dependency requirements without")
    lines.append("downloading the full package (which may be very large).")
    lines.append("")
    lines.append("## Note")
    lines.append("")
    lines.append("This package provides minimal stubs. Importing it will raise an ImportError")
    lines.append("explaining that the real package is not installed.")
    
    return "\n".join(lines)


def file_hash_record(content):
    """Generate sha256 hash in RECORD format and file size."""
    if isinstance(content, str):
        content = content.encode('utf-8')
    digest = hashlib.sha256(content).digest()
    # URL-safe base64 without padding
    hash_b64 = base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')
    return f"sha256={hash_b64}", len(content)


def create_dummy_wheel(package_name, version, include_deps=False):
    """
    Create a minimal dummy wheel package with proper METADATA.
    The METADATA is generated using generate_metadata_file() to ensure
    it's readable by uv, pip, and other tools.
    """
    try:
        print(f"  📝 Generating metadata for {package_name} {version}...")
        
        # Normalize package name for wheel internals (underscore)
        wheel_name = package_name.lower().replace('-', '_')
        dist_info_name = f"{wheel_name}-{version}.dist-info"
        
        # Prepare all file contents
        files = {}
        
        # 1. Package __init__.py
        init_content = f'''# -*- coding: utf-8 -*-
"""
Dummy {package_name} package - stub generated by PyPI Proxy.

This is NOT the real {package_name} package. It's a minimal stub
to satisfy dependency requirements without the full installation.
"""

__version__ = "{version}"
__author__ = "PyPI Proxy (stub)"
__all__ = ["__version__"]


class _StubModule:
    """Stub that raises ImportError on any attribute access."""
    
    def __init__(self, name):
        self._name = name
    
    def __getattr__(self, attr):
        raise ImportError(
            f"Cannot import '{{attr}}' from dummy stub package '{package_name}'. "
            f"The real '{package_name}' package is not installed. "
            f"Install it with: pip install {package_name}"
        )
    
    def __call__(self, *args, **kwargs):
        raise ImportError(
            f"Cannot call dummy stub package '{package_name}'. "
            f"The real '{package_name}' package is not installed."
        )


# Make any submodule access fail gracefully with clear error
def __getattr__(name):
    if name.startswith('_'):
        raise AttributeError(name)
    return _StubModule(f"{package_name}.{{name}}")
'''
        files[f"{wheel_name}/__init__.py"] = init_content
        
        # 2. METADATA - THE CRITICAL FILE
        # Use generate_metadata_file to create proper, compliant metadata
        metadata_content = generate_metadata_file(package_name, version, include_deps)
        files[f"{dist_info_name}/METADATA"] = metadata_content
        print(f"  ✓ Generated METADATA ({len(metadata_content)} bytes)")
        
        # 3. WHEEL file
        wheel_content = """Wheel-Version: 1.0
Generator: pypi-proxy (1.0.0)
Root-Is-Purelib: true
Tag: py3-none-any
"""
        files[f"{dist_info_name}/WHEEL"] = wheel_content
        
        # 4. top_level.txt
        top_level_content = f"{wheel_name}\n"
        files[f"{dist_info_name}/top_level.txt"] = top_level_content
        
        # 5. INSTALLER
        installer_content = "uv\n"
        files[f"{dist_info_name}/INSTALLER"] = installer_content
        
        # 6. direct_url.json (optional but helps some tools)
        direct_url_content = json.dumps({
            "url": f"http://localhost:8080/packages/{wheel_name}-{version}-py3-none-any.whl",
            "archive_info": {}
        }, indent=2)
        files[f"{dist_info_name}/direct_url.json"] = direct_url_content
        
        # 7. Build RECORD with proper hashes (must be last)
        record_lines = []
        for filepath, content in files.items():
            if isinstance(content, str):
                content_bytes = content.encode('utf-8')
            else:
                content_bytes = content
            hash_str, size = file_hash_record(content_bytes)
            record_lines.append(f"{filepath},{hash_str},{size}")
        
        # RECORD itself has no hash (per PEP 376)
        record_lines.append(f"{dist_info_name}/RECORD,,")
        record_content = "\n".join(record_lines) + "\n"
        files[f"{dist_info_name}/RECORD"] = record_content
        
        # Create the wheel zip file
        temp_wheel = tempfile.NamedTemporaryFile(delete=False, suffix='.whl')
        temp_wheel.close()
        
        try:
            with zipfile.ZipFile(temp_wheel.name, 'w', zipfile.ZIP_DEFLATED) as wheel:
                for filepath, content in files.items():
                    if isinstance(content, str):
                        content = content.encode('utf-8')
                    # Set proper file permissions in zip
                    info = zipfile.ZipInfo(filepath)
                    info.external_attr = 0o644 << 16  # rw-r--r--
                    wheel.writestr(info, content)
            
            # Read the wheel content
            with open(temp_wheel.name, 'rb') as f:
                wheel_bytes = f.read()
            
            print(f"  ✓ Created wheel: {len(files)} files, {len(wheel_bytes)} bytes")
            
            # Debug: list contents
            print(f"  📦 Wheel contents:")
            for f in files.keys():
                print(f"      - {f}")
            
            return wheel_bytes
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_wheel.name):
                os.unlink(temp_wheel.name)
        
    except Exception as e:
        print(f"  ✗ Error creating wheel: {e}")
        import traceback
        traceback.print_exc()
        return None


def analyze_dependencies(package_name):
    """Analyze what versions a package requires for its dependencies."""
    print(f"\n🔍 Analyzing dependencies for: {package_name}\n")
    
    info = fetch_package_info(package_name)
    if not info:
        print("Failed to fetch package info")
        return
    
    latest_version = info.get('info', {}).get('version', 'unknown')
    print(f"Latest version: {latest_version}\n")
    
    requires_dist = info.get('info', {}).get('requires_dist', [])
    if not requires_dist:
        print("No dependencies found")
        return
    
    print("Dependencies:")
    print("-" * 60)
    
    for req in requires_dist:
        req_clean = req.split(';')[0].strip()
        match = re.match(r'([a-zA-Z0-9\-_]+)(.*)', req_clean)
        if match:
            dep_name = match.group(1).lower()
            version_spec = match.group(2).strip()
            
            if dep_name in DUMMY_PACKAGES:
                if version_spec:
                    suggested_version = find_compatible_version(dep_name, version_spec)
                    print(f"  📦 {dep_name:30} {version_spec:20} → {suggested_version}")
                else:
                    print(f"  📦 {dep_name:30} (any version)")


class PyPIProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_HEAD(self):
        path = self.path
        package_name = self._extract_package_name(path)
        
        if package_name and package_name in DUMMY_PACKAGES:
            if '/simple/' in path:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
            elif path.endswith('.whl') or path.endswith('.tar.gz'):
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', '10000')
                self.end_headers()
            else:
                self._proxy_request_head()
        else:
            self._proxy_request_head()

    def do_GET(self):
        path = self.path
        package_name = self._extract_package_name(path)
        
        print(f"\n{'='*60}")
        print(f"📍 REQUEST: {path}")
        if package_name:
            is_dummy = package_name in DUMMY_PACKAGES
            print(f"   Package: {package_name}")
            print(f"   Is Dummy: {is_dummy}")
        
        if package_name and package_name in DUMMY_PACKAGES:
            print(f"📦 Handling as DUMMY package")
            if '/simple/' in path:
                self._serve_dummy_simple_page(package_name)
            elif path.endswith('.whl') or path.endswith('.tar.gz'):
                self._serve_dummy_package(package_name)
            else:
                self._proxy_request()
        else:
            if package_name:
                print(f"🌐 Proxying to PyPI")
            self._proxy_request()

    def _extract_package_name(self, path):
        """Extract and normalize package name from request path."""
        if '/simple/' in path:
            parts = path.split('/simple/')
            if len(parts) > 1:
                name = parts[1].rstrip('/').split('/')[0]
                # Normalize: lowercase, replace underscores with hyphens (PEP 503)
                return name.lower().replace('_', '-')
        elif '/packages/' in path:
            filename = os.path.basename(path)
            # Match package name before version number
            match = re.match(r'^([a-zA-Z0-9_-]+)-\d', filename)
            if match:
                name = match.group(1)
                return name.lower().replace('_', '-')
        return None

    def _serve_dummy_simple_page(self, package_name):
        """Serve the simple index page for a dummy package."""
        version_spec = DUMMY_PACKAGES.get(package_name, '99.0.0')
        
        if version_spec == 'auto':
            version = find_compatible_version(package_name)
            print(f"  🤖 Auto-detected version: {version}")
        else:
            version = version_spec
        
        # Use underscore for wheel filename (PEP 427)
        wheel_name = package_name.replace('-', '_')
        
        # Serve multiple versions for compatibility
        versions_to_serve = [version]
        try:
            v = Version(version)
            if v.minor > 0:
                older1 = f"{v.major}.{v.minor - 1}.0"
                versions_to_serve.append(older1)
            if v.minor > 1:
                older2 = f"{v.major}.{v.minor - 2}.0"
                versions_to_serve.append(older2)
        except:
            pass
        
        links = []
        for ver in versions_to_serve:
            fname = f"{wheel_name}-{ver}-py3-none-any.whl"
            links.append(
                f'    <a href="/packages/{fname}" data-requires-python="&gt;=3.8">{fname}</a><br/>'
            )
        
        html = f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Links for {package_name}</title>
  </head>
  <body>
    <h1>Links for {package_name}</h1>
{chr(10).join(links)}
  </body>
</html>
"""
        
        content = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(content))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(content)
        print(f"  ✓ Served simple page: {package_name}")
        print(f"    Versions: {', '.join(versions_to_serve)}")

    def _serve_dummy_package(self, package_name):
        """Serve the actual dummy wheel file."""
        filename = os.path.basename(self.path)
        
        # Extract version from filename
        # Format: {name}-{version}-py3-none-any.whl
        version_match = re.search(r'-(\d+\.\d+\.\d+(?:\.\w+)?)-', filename)
        
        if version_match:
            version = version_match.group(1)
        else:
            version_spec = DUMMY_PACKAGES.get(package_name, '99.0.0')
            if version_spec == 'auto':
                version = find_compatible_version(package_name)
            else:
                version = version_spec
        
        print(f"  🔨 Building wheel: {package_name} v{version}")
        
        # Create the wheel with proper METADATA
        content = create_dummy_wheel(package_name, version, include_deps=False)
        
        if content:
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header('Content-Length', len(content))
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(content)
            print(f"  ✓ Served wheel: {filename} ({len(content)} bytes)")
        else:
            self.send_error(500, "Failed to build dummy package")
            print(f"  ✗ Failed to build wheel")

    def _proxy_request_head(self):
        url = f"{PYPI_INDEX}{self.path}"
        try:
            req = urllib.request.Request(url, method='HEAD')
            req.add_header('User-Agent', 'pypi-proxy/1.0')
            with urllib.request.urlopen(req, timeout=30) as response:
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in ['transfer-encoding', 'connection']:
                        self.send_header(key, value)
                self.end_headers()
        except urllib.error.HTTPError as e:
            self.send_error(e.code, e.reason)
        except Exception as e:
            self.send_error(502, f"Proxy error: {str(e)}")

    def _proxy_request(self):
        url = f"{PYPI_INDEX}{self.path}"
        try:
            headers = {'User-Agent': 'pypi-proxy/1.0'}
            for key, value in self.headers.items():
                if key.lower() not in ['host', 'connection']:
                    headers[key] = value
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in ['transfer-encoding', 'connection']:
                        self.send_header(key, value)
                self.end_headers()
                shutil.copyfileobj(response, self.wfile)
        except urllib.error.HTTPError as e:
            self.send_error(e.code, e.reason)
        except Exception as e:
            self.send_error(502, f"Proxy error: {str(e)}")


def run_server(port=8080):
    server_address = ('', port)
    httpd = HTTPServer(server_address, PyPIProxyHandler)
    
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║   Smart PyPI Proxy with Auto-Generated METADATA                 ║
╠══════════════════════════════════════════════════════════════════╣
║   Server: http://localhost:{port:<5}                                ║
║   Index:  http://localhost:{port}/simple/                          ║
╚══════════════════════════════════════════════════════════════════╝

📦 Dummy packages (replaced with tiny stubs):
""")
    for pkg in sorted(DUMMY_PACKAGES.keys()):
        print(f"   • {pkg}")
    
    print(f"""
All other packages are proxied from PyPI.

Usage:
  uv pip install --index-url http://localhost:{port}/simple/ <package>
  pip install --index-url http://localhost:{port}/simple/ <package>

Features:
  ✓ Auto-detects latest compatible versions from PyPI
  ✓ Generates valid METADATA files (PEP 566 compliant)
  ✓ Creates proper wheel structure with RECORD hashes

Press Ctrl+C to stop.
""")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down server...")
        httpd.shutdown()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--analyze' and len(sys.argv) > 2:
            analyze_dependencies(sys.argv[2])
        elif sys.argv[1] == '--test-wheel':
            # Test wheel generation
            pkg = sys.argv[2] if len(sys.argv) > 2 else 'torch'
            ver = sys.argv[3] if len(sys.argv) > 3 else '2.0.0'
            print(f"Testing wheel generation for {pkg} {ver}...")
            wheel_data = create_dummy_wheel(pkg, ver)
            if wheel_data:
                out_file = f"{pkg.replace('-','_')}-{ver}-py3-none-any.whl"
                with open(out_file, 'wb') as f:
                    f.write(wheel_data)
                print(f"✓ Wrote: {out_file}")
                # Show contents
                print("\nWheel contents:")
                with zipfile.ZipFile(out_file, 'r') as zf:
                    for name in zf.namelist():
                        info = zf.getinfo(name)
                        print(f"  {name} ({info.file_size} bytes)")
                    # Show METADATA
                    for name in zf.namelist():
                        if name.endswith('/METADATA'):
                            print(f"\n{'='*60}")
                            print(f"METADATA content:")
                            print('='*60)
                            print(zf.read(name).decode('utf-8'))
        elif sys.argv[1] == '--test-metadata':
            pkg = sys.argv[2] if len(sys.argv) > 2 else 'torch'
            ver = sys.argv[3] if len(sys.argv) > 3 else '2.0.0'
            print(generate_metadata_file(pkg, ver, include_real_deps=True))
        else:
            print("Usage:")
            print("  python pypi_proxy.py                    # Run server")
            print("  python pypi_proxy.py --analyze PACKAGE  # Analyze dependencies")
            print("  python pypi_proxy.py --test-wheel [PKG] [VER]  # Test wheel generation")
            print("  python pypi_proxy.py --test-metadata [PKG] [VER]  # Test metadata")
    else:
        run_server()
