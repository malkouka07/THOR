#!/usr/bin/env bash
# Convert standardized RePLaT NetCDF files to GRIB2 with explicit WMO parameters.
#
# GRIB2 discipline/category/number mappings:
#   eastward wind       0/2/2  -> CDO setparam 2.2.0
#   northward wind      0/2/3  -> CDO setparam 3.2.0
#   pressure omega      0/2/8  -> CDO setparam 8.2.0
#   geometric vertical  0/2/9  -> CDO setparam 9.2.0
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
    echo "ERROR: CDO is required for GRIB2 conversion." >&2
    exit 2
fi

mkdir -p "$output_dir"
log_dir=$(dirname "$output_dir")/logs
mkdir -p "$log_dir"
log_file=$log_dir/grib2_conversion.log

shopt -s nullglob
inputs=("$input_dir"/*.nc)
if [[ ${#inputs[@]} -eq 0 ]]; then
    echo "ERROR: no NetCDF files in $input_dir" >&2
    exit 2
fi

work_dir=$(mktemp -d "$output_dir/.grib_work.XXXXXX")
cleanup() {
    rm -rf -- "$work_dir"
}
trap cleanup EXIT

for input in "${inputs[@]}"; do
    base=$(basename "$input" .nc)
    output=$output_dir/$base.grib2
    if [[ -e "$output" && $overwrite != true ]]; then
        echo "ERROR: refusing to overwrite $output (use --overwrite)" >&2
        exit 2
    fi

    components=()
    if ! cdo -s showname "$input" | tr ' ' '\n' | grep -qx eastward_wind; then
        echo "ERROR: eastward_wind missing from $input" >&2
        exit 2
    fi
    if ! cdo -s showname "$input" | tr ' ' '\n' | grep -qx northward_wind; then
        echo "ERROR: northward_wind missing from $input" >&2
        exit 2
    fi

    cdo -s -f grb2 \
        -setparam,2.2.0 -setname,u -selname,eastward_wind \
        "$input" "$work_dir/u.grib2"
    components+=("$work_dir/u.grib2")

    cdo -s -f grb2 \
        -setparam,3.2.0 -setname,v -selname,northward_wind \
        "$input" "$work_dir/v.grib2"
    components+=("$work_dir/v.grib2")

    names=$(cdo -s showname "$input")
    if tr ' ' '\n' <<<"$names" | grep -qx upward_air_velocity; then
        cdo -s -f grb2 \
            -setparam,9.2.0 -setname,wz -selname,upward_air_velocity \
            "$input" "$work_dir/vertical.grib2"
        components+=("$work_dir/vertical.grib2")
        vertical_note="geometric W: GRIB2 0/2/9"
    elif tr ' ' '\n' <<<"$names" | grep -qx lagrangian_tendency_of_air_pressure; then
        cdo -s -f grb2 \
            -setparam,8.2.0 -setname,omega -selname,lagrangian_tendency_of_air_pressure \
            "$input" "$work_dir/vertical.grib2"
        components+=("$work_dir/vertical.grib2")
        vertical_note="omega: GRIB2 0/2/8"
    else
        vertical_note="vertical variable skipped: no unambiguous standardized variable"
    fi

    temporary=$output.partial
    rm -f -- "$temporary"
    cdo -s merge "${components[@]}" "$temporary"
    mv -f -- "$temporary" "$output"

    input_times=$(cdo -s ntime "$input")
    output_times=$(cdo -s ntime "$output")
    input_levels=$(cdo -s nlevel "$input" | sort -u | tr -d '[:space:]')
    output_levels=$(cdo -s nlevel "$output" | sort -u | tr -d '[:space:]')
    if [[ $input_times != "$output_times" || $input_levels != "$output_levels" ]]; then
        echo "ERROR: time/level count changed for $output" >&2
        exit 2
    fi
    input_level_values=$(cdo -s showlevel "$input" | head -n 1 | xargs)
    output_level_values=$(cdo -s showlevel "$output" | head -n 1 | xargs)
    input_timestamps=$(cdo -s showtimestamp "$input" | xargs)
    output_timestamps=$(cdo -s showtimestamp "$output" | xargs)
    if [[ $input_level_values != "$output_level_values" ]]; then
        echo "ERROR: pressure-level values changed for $output" >&2
        exit 2
    fi
    if [[ $input_timestamps != "$output_timestamps" ]]; then
        echo "ERROR: timestamps changed for $output" >&2
        exit 2
    fi
    if ! cdo -s sinfo "$output" >/dev/null; then
        echo "ERROR: CDO cannot reopen $output" >&2
        exit 2
    fi
    {
        printf '%s -> %s; times=%s; levels=%s; timestamps/level-values=identical; %s; parameters=' \
            "$input" "$output" "$output_times" "$output_levels" "$vertical_note"
        cdo -s showparam "$output"
    } >>"$log_file"
    rm -f -- "$work_dir"/*.grib2
    echo "Created $output"
done
