#!/usr/bin/env bash
# Builds a reproducible Linux x86_64 release package.
#
# Must run ON Linux — the PyInstaller runtime bundle is not cross-compiled.
# For a Windows package, run deployment\build-release-windows.ps1 on Windows.
#
# Does NOT run the test suite (see the section-27/section-14 verification
# sequence for that) and does NOT touch git. Safe to re-run; each run starts
# from a clean deployment/pyinstaller/{build,dist} and dist-release/ output.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "${REPO_ROOT}"

VERSION="$(python3 -c 'import re; print(re.search(r"__version__ = \"([^\"]+)\"", open("agent/app/_version.py").read())[1])')"
PACKAGE_NAME="Willhaben-Suchagent-${VERSION}-linux-x86_64"
OUTPUT_DIR="${REPO_ROOT}/dist-release"
STAGE_DIR="${OUTPUT_DIR}/${PACKAGE_NAME}"

echo "Building release ${VERSION} for linux-x86_64"
echo

echo "== 1/6: Building the Firefox extension =="
(
  cd "${REPO_ROOT}/extension"
  npm ci
  npm run build
)

echo
echo "== 2/6: Packaging extension/dist as an .xpi =="
XPI_PATH="${OUTPUT_DIR}/willhaben-suchagent-${VERSION}-firefox.xpi"
mkdir -p "${OUTPUT_DIR}"
rm -f "${XPI_PATH}"
(
  cd "${REPO_ROOT}/extension/dist"
  # No source maps, no test files: `npm run build` (vite) only ever emits the
  # production bundle into dist/, nothing dev-only is ever written there.
  zip -X -r -q "${XPI_PATH}" . -x '*.map'
)

echo
echo "== 3/6: Building the Python runtime with PyInstaller =="
BUILD_VENV="${REPO_ROOT}/.build-venv"
if [[ ! -d "${BUILD_VENV}" ]]; then
  python3 -m venv "${BUILD_VENV}"
fi
"${BUILD_VENV}/bin/pip" install --quiet --upgrade pip
"${BUILD_VENV}/bin/pip" install --quiet -e "${REPO_ROOT}[build]"
rm -rf "${REPO_ROOT}/deployment/pyinstaller/build" "${REPO_ROOT}/deployment/pyinstaller/dist"
(
  cd "${REPO_ROOT}/deployment/pyinstaller"
  "${BUILD_VENV}/bin/pyinstaller" --noconfirm --clean willhaben-suchagent.spec
)

echo
echo "== 4/6: Assembling the release folder =="
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}/extension"
cp -r "${REPO_ROOT}/deployment/pyinstaller/dist/runtime" "${STAGE_DIR}/runtime"
cp "${REPO_ROOT}/deployment/release-templates/linux/Einrichtung.sh" "${STAGE_DIR}/Einrichtung.sh"
cp "${REPO_ROOT}/deployment/release-templates/linux/Willhaben-Suchagent starten.sh" "${STAGE_DIR}/Willhaben-Suchagent starten.sh"
chmod +x "${STAGE_DIR}/Einrichtung.sh" "${STAGE_DIR}/Willhaben-Suchagent starten.sh"
cp "${XPI_PATH}" "${STAGE_DIR}/extension/willhaben-suchagent.xpi"
cp "${REPO_ROOT}/USER_GUIDE.md" "${STAGE_DIR}/USER_GUIDE.md"
cp "${REPO_ROOT}/CHANGELOG.md" "${STAGE_DIR}/CHANGELOG.md"

echo
echo "== 5/6: Creating the release archive =="
(
  cd "${OUTPUT_DIR}"
  tar -czf "${PACKAGE_NAME}.tar.gz" "${PACKAGE_NAME}"
)

echo
echo "== 6/6: Writing checksums =="
(
  cd "${OUTPUT_DIR}"
  sha256sum "${PACKAGE_NAME}.tar.gz" "$(basename "${XPI_PATH}")" > SHA256SUMS.linux
)

echo
echo "Done. Release artifacts in ${OUTPUT_DIR}:"
echo "  ${PACKAGE_NAME}.tar.gz"
echo "  $(basename "${XPI_PATH}")"
echo "  SHA256SUMS.linux"
