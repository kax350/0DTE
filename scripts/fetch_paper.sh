#!/usr/bin/env bash
# Re-download the audited paper and verify it is the exact version read.
set -euo pipefail
mkdir -p paper/tex_source
curl -sSL -o paper/arXiv-2608.24786v1.pdf https://arxiv.org/pdf/2608.24786v1
curl -sSL https://arxiv.org/e-print/2608.24786v1 | tar -xz -C paper/tex_source
echo "7ddf3853c5757f2273c40ed3c24b10aad048b4e9cf13b51b627790e8c480bd08  paper/arXiv-2608.24786v1.pdf" | sha256sum -c
echo "896b5d66a00dcaa9b0269b1b88e0427fcfff1fd8d0c180792e0f27ca53de2ece  paper/tex_source/main.tex" | sha256sum -c
