#!/usr/bin/env bash
# Convert the standardized RePLaT NetCDF4 files to legacy-compatible
# NetCDF3 classic (CDF-1) files while preserving data and metadata values.
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

for required_command in basename cdo diff mv ncks od rm sed tr; do
    if ! command -v "$required_command" >/dev/null 2>&1; then
        echo "ERROR: $required_command is required for conversion." >&2
        exit 2
    fi
done

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
    # -3 selects NetCDF3 classic and -h prevents tool-generated history
    # entries. NetCDF3 has no 64-bit integer type, so NCO safely stores the
    # small source_output_index attribute as int32 with the same value.
    ncks -O -h -3 "$input" "$temporary"

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
        echo "ERROR: decoded values changed for $input:" >&2
        echo "$diff_output" >&2
        exit 1
    fi

    # Compare all global and variable metadata after normalizing the only
    # intentional storage-type change: int64 to int32 for source_output_index.
    metadata_diff=$(
        diff -u \
            <(
                ncks -m -M "$input" |
                        sed -E \
                        -e '1s/^netcdf .* \{/netcdf FILE {/' \
                        -e 's/(:source_output_index = [0-9]+)ll([[:space:]]*;)/\1\2/'
            ) \
            <(
                ncks -m -M "$temporary" |
                    sed -E '1s/^netcdf .* \{/netcdf FILE {/'
            ) || true
    )
    if [[ -n $metadata_diff ]]; then
        rm -f -- "$temporary"
        echo "ERROR: metadata values changed for $input:" >&2
        echo "$metadata_diff" >&2
        exit 1
    fi

    mv -f -- "$temporary" "$output"
    echo "Wrote $output"
done
