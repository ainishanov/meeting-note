# Third-party notices

Meeting Note is distributed under the MIT License. Its Windows package also
contains open-source dependencies with their own licenses.

## Qt for Python

The user interface uses Qt for Python (`PySide6`, `PySide6_Essentials`,
`PySide6_Addons`, and `shiboken6`) under the GNU Lesser General Public License
version 3 option. Qt for Python is available under LGPLv3/GPLv3 and commercial
terms; Meeting Note uses the open-source LGPLv3 option and does not modify Qt or
PySide6.

- Project and source: https://code.qt.io/cgit/pyside/pyside-setup.git/
- License information: https://doc.qt.io/qtforpython-6/licenses.html
- LGPLv3 text: https://www.gnu.org/licenses/lgpl-3.0.html

Meeting Note's complete application source and build workflow are available at
https://github.com/ainishanov/meeting-note. Users may rebuild the application
against a compatible or modified Qt for Python version. Exact dependency
versions used for an official release are recorded in `requirements-lock.txt`.

## Other dependencies

The application also uses packages under OSI-approved licenses, including
Apache-2.0, BSD, MIT, PSF, and LGPL licenses. Package names and exact versions
are recorded in `requirements-lock.txt`; their license metadata and license
files are included in their corresponding source distributions.

This notice does not replace the license terms of any dependency.
