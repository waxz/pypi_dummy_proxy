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
from pathlib import Path
from packaging.specifiers import SpecifierSet
from packaging.version import Version

# IMPORTANT: Only add packages HERE that you want to REPLACE with dummy versions
# These packages will be tiny stubs instead of real packages
DUMMY_PACKAGES = {
    'torch': 'auto',
    'torchvision': 'auto',
    'torchaudio': 'auto',
}

PYPI_INDEX = "https://pypi.org"
VERSION_CACHE = {}

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

def create_dummy_wheel(package_name, version):
    """Create a minimal dummy wheel package directly."""
    try:
        # Normalize package name for directory
        pkg_dir_name = package_name.replace('-', '_')
        
        # Create wheel filename
        wheel_filename = f"{package_name}-{version}-py3-none-any.whl"
        
        # Create a temporary file for the wheel
        temp_wheel = tempfile.NamedTemporaryFile(delete=False, suffix='.whl')
        temp_wheel.close()
        
        with zipfile.ZipFile(temp_wheel.name, 'w', zipfile.ZIP_DEFLATED) as wheel:
            # Add __init__.py
            init_content = f'"""Dummy {package_name} package."""\n__version__ = "{version}"\n'
            wheel.writestr(f"{pkg_dir_name}/__init__.py", init_content)
            
            # Add METADATA
            metadata = f"""Metadata-Version: 2.1
Name: {package_name}
Version: {version}
Summary: Dummy package for {package_name}
Home-page: https://example.com
Author: PyPI Proxy
Author-email: proxy@example.com
License: MIT
Platform: any
Requires-Python: >=3.6
"""
            wheel.writestr(f"{pkg_dir_name}-{version}.dist-info/METADATA", metadata)
            
            # Add WHEEL
            wheel_info = """Wheel-Version: 1.0
Generator: pypi-proxy
Root-Is-Purelib: true
Tag: py3-none-any
"""
            wheel.writestr(f"{pkg_dir_name}-{version}.dist-info/WHEEL", wheel_info)
            
            # Add RECORD
            record = f"""{pkg_dir_name}/__init__.py,,
{pkg_dir_name}-{version}.dist-info/METADATA,,
{pkg_dir_name}-{version}.dist-info/WHEEL,,
{pkg_dir_name}-{version}.dist-info/RECORD,,
"""
            wheel.writestr(f"{pkg_dir_name}-{version}.dist-info/RECORD", record)
            
            # Add top_level.txt
            wheel.writestr(f"{pkg_dir_name}-{version}.dist-info/top_level.txt", pkg_dir_name)
        
        # Read the wheel content
        with open(temp_wheel.name, 'rb') as f:
            content = f.read()
        
        # Clean up
        os.unlink(temp_wheel.name)
        
        return content
        
    except Exception as e:
        print(f"  ✗ Error creating wheel: {e}")
        import traceback
        traceback.print_exc()
        return None

class PyPIProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_HEAD(self):
        path = self.path
        package_name = self._extract_package_name(path)
        
        if package_name and package_name in DUMMY_PACKAGES:
            if '/simple/' in path:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
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
        
        print(f"📍 REQUEST: {path}")
        if package_name:
            print(f"   Package: {package_name}, In DUMMY_PACKAGES: {package_name in DUMMY_PACKAGES}")
        
        if package_name and package_name in DUMMY_PACKAGES:
            print(f"📦 GET  [DUMMY] {package_name}")
            if '/simple/' in path:
                self._serve_dummy_simple_page(package_name)
            elif path.endswith('.whl') or path.endswith('.tar.gz'):
                self._serve_dummy_package(package_name)
            else:
                self._proxy_request()
        else:
            if package_name:
                print(f"🌐 GET  [PROXY] {package_name}")
            self._proxy_request()

    def _extract_package_name(self, path):
        if '/simple/' in path:
            parts = path.split('/simple/')
            if len(parts) > 1:
                name = parts[1].rstrip('/').split('/')[0]
                return name.lower().replace('_', '-')
        elif '/packages/' in path:
            filename = os.path.basename(path)
            if '-' in filename:
                parts = filename.split('-')
                return parts[0].lower()
        return None

    def _serve_dummy_simple_page(self, package_name):
        version_spec = DUMMY_PACKAGES.get(package_name, '99.0.0')
        
        if version_spec == 'auto':
            version = find_compatible_version(package_name)
            print(f"  🤖 Auto-detected version: {version}")
        else:
            version = version_spec
        
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
            fname = f"{package_name}-{ver}-py3-none-any.whl"
            links.append(f'<a href="/packages/{fname}#sha256=dummy">{fname}</a><br/>')
        
        html = f"""<!DOCTYPE html>
<html>
<head><title>Links for {package_name}</title></head>
<body>
<h1>Links for {package_name}</h1>
{''.join(links)}
</body>
</html>"""
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', len(html.encode()))
        self.end_headers()
        self.wfile.write(html.encode())
        print(f"  ✓ Served index page for {package_name} v{version} (+{len(versions_to_serve)-1} older)")

    def _serve_dummy_package(self, package_name):
        filename = os.path.basename(self.path)
        version_match = re.search(r'-(\d+\.\d+\.\d+[^-]*)-', filename)
        
        if version_match:
            version = version_match.group(1)
        else:
            version_spec = DUMMY_PACKAGES.get(package_name, '99.0.0')
            if version_spec == 'auto':
                version = find_compatible_version(package_name)
            else:
                version = version_spec
        
        print(f"  🔨 Building wheel for {package_name} v{version}")
        
        content = create_dummy_wheel(package_name, version)
        
        if content:
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
            print(f"  ✓ Served wheel for {package_name} v{version} ({len(content)} bytes)")
        else:
            self.send_error(500, "Failed to build dummy package")
            print(f"  ✗ Failed to build wheel for {package_name}")

    def _proxy_request_head(self):
        url = f"{PYPI_INDEX}{self.path}"
        try:
            req = urllib.request.Request(url, method='HEAD')
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
            headers = {}
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
╔════════════════════════════════════════════════════════════════╗
║        Smart PyPI Proxy with Auto Version Detection           ║
╚════════════════════════════════════════════════════════════════╝

Server running on: http://localhost:{port}

Dummy packages (will be replaced with tiny stubs):
""")
    for pkg in sorted(DUMMY_PACKAGES.keys()):
        print(f"  • {pkg}")
    
    print(f"""
All other packages will be fetched from PyPI normally.

Usage:
  uv pip install --index-url http://localhost:{port}/simple/ open-webui

Press Ctrl+C to stop the server.
""")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
        httpd.shutdown()

if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == '--analyze' and len(sys.argv) > 2:
            analyze_dependencies(sys.argv[2])
        else:
            print("Usage:")
            print("  python pypi_proxy.py                    # Run server")
            print("  python pypi_proxy.py --analyze PACKAGE  # Analyze dependencies")
    else:
        run_server()
