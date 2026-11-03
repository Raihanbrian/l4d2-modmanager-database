# License and attribution

Original project source and documentation are licensed under the [MIT License](../LICENSE).
Copyright (c) 2026 RABrian. The project owner approved this license for the first
GitHub publication. The copyright and permission notices must accompany copies
or substantial portions of the Software; see LICENSE for the full terms.

Third-party code, runtime libraries, Steam data, Workshop assets and trademarks
retain their own terms. This source license approval does not clear the remaining
binary redistribution checks or authorize a public release automatically.

## Runtime components

| Component | Review |
|---|---|
| CPython 3.14.6 and bundled standard-library notices | Original PSF license included |
| Tcl/Tk 8.6.15 | Original permissive license notices included |
| Pillow 12.3.0 and included codecs | Original combined license/codec notices included |
| OpenSSL 3.5.7 | Apache-2.0 LICENSE included; OpenSSL Project Authors attribution |
| libffi 3.4.4, Expat, zlib-ng 2.2.4, Zstandard 1.5.7, XZ 5.2.5 | Original relevant upstream notices included |
| SQLite 3.50.4 | Upstream public-domain dedication; synthetic demo is project-authored |
| PyInstaller 6.22.3 | Bootloader exception permits separately licensed bundled apps, subject to dependency terms |
| Windows C runtime DLLs | VCRUNTIME140.dll and VCRUNTIME140_1.dll from the CPython installation; original Windows binary conditions retained in python-LICENSE.txt |

The bundled license texts are in the portable `licenses` directory. This software
is based in part on the work of the Independent JPEG Group. Pillow's combined
notice retains its codec authors' terms, including libjpeg-turbo. Source runtime
dependencies are Python's standard library plus the optional Pillow desktop
extra; build-only dependencies are pinned separately in requirements-build.txt.

References: [CPython license](https://docs.python.org/3/license.html),
[CPython Windows dependency pins](https://github.com/python/cpython/blob/v3.14.6/PCbuild/get_externals.bat),
[Pillow licensing](https://pillow.readthedocs.io/en/stable/about.html#license),
[PyInstaller exception](https://pyinstaller.org/en/stable/license.html),
[Microsoft redistributable guidance](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170),
[SQLite public domain](https://www.sqlite.org/copyright.html).

The release build restricts DLL discovery to the selected Python installation and
Windows. The two VCRUNTIME DLLs are collected from CPython; the complete original
Python license, including its Windows binary distribution conditions, is retained.
The rebuilt Windows 10/11 package does not ship separately collected UCRT or
API-set forwarding DLLs from unrelated build tools. Windows supplies its UCRT.
Microsoft components retain their own terms and are not relicensed under MIT.
The final binary and notices remain subject to the owner's publication review.

## Steam and screenshots

[Valve's API terms](https://steamcommunity.com/dev/apiterms) cover public Steam
metadata separately from source-code licensing. API access can change; keyless
public endpoint availability is an observation, not permanent permission or an
availability promise. Requests are scoped, cache bounded and data source labelled;
the project operates no metadata server or subscription-management service.
See [privacy behavior](PRIVACY.md). Final publication/terms review remains with
the owner; no scraping or authentication workaround is implemented.

Public screenshots in `docs/screenshots/m64` use fictional names, synthetic VPKs
and generated letter thumbnails. They contain no real Workshop artwork or owner's
catalog data. Historical real-collection screenshots, personal databases, private
handoffs and review archives are excluded from the public source ZIP. No Workshop
content is redistributed. Original game identifiers are factual references; source
URLs for target dictionaries remain in the code and are not an external code copy.
