#!/usr/bin/env bash
# Convert the standardized RePLaT NetCDF4 files to legacy-compatible
# NetCDF3 classic (CDF-1) files without changing the decoded data or metadata.
set -euo pipefail

usage() {
    echo "Usage: $0 INPUT_DIR OUTPUT_DIR [--overwrite]" >&2
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
    usage
    exit 2
fi

input_dir=$1
output_dir=$2
overwrite=false
if [[ ${3:-} == "--overwrite" ]]; then
    overwrite=true
elif [[ $# -eq 3 ]]; then
    usage
    exit 2
fi

if ! command -v cdo >/dev/null 2>&1; then
    echo "ERROR: CDO is required for NetCDF3 conversion." >&2
    exit 2
fi

mkdir -p "$output_dir"

shopt -s nullglob
inputs=("$input_dir"/*.nc)
if [[ ${#inputs[@]} -eq 0 ]]; then
    echo "ERROR: no NetCDF files in $input_dir" >&2
    exit 2
fi

for input in "${inputs[@]}"; do
    base=$(basename "$input" .nc)
    output=$output_dir/${base}_motus_nc3_classic.nc
    temporary=$output.partial

    if [[ -e "$output" && $overwrite != true ]]; then
        echo "ERROR: refusing to overwrite $output (use --overwrite)" >&2
        exit 2
    fi

    rm -f -- "$temporary"
    cdo -s -f nc1 copy "$input" "$temporary"

    # A NetCDF3 classic file starts with the four-byte CDF-1 signature.
    signature=$(od -An -tx1 -N4 "$temporary" | tr -d '[:space:]')
    if [[ $signature != "43444601" ]]; then
        rm -f -- "$temporary"
        echo "ERROR: $input did not produce a NetCDF3 classic (CDF-1) file." >&2
        exit 1
    fi

    # CDO emits no diffn output when all decoded records are identical.
    diff_output=$(cdo -s diffn "$input" "$temporary" 2>&1)
    if [[ -n $diff_output ]]; then
        rm -f -- "$temporary"
        echo "ERROR: decoded values or metadata changed for $input:" >&2
        echo "$diff_output" >&2
        exit 1
    fi

    mv -f -- "$temporary" "$output"
    echo "Wrote $output"
done

