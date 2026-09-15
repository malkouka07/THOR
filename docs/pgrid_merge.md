# `pgrid_merge`

`pgrid_merge` is a helper for cleaning up fragmented pressure-grid regrids in a THOR results directory.

It is meant for cases where pressure-coordinate regridding was run in several partial chunks, for example:

- `pgrid_1000_1020_1/`
- `pgrid_1000_1050_1/`
- `pgrid_1000_1500_1/`

Instead of manually comparing those folders and copying files around, `pgrid_merge` scans all available `pgrid_*` directories, merges the pressure regrid files into one canonical folder, resolves duplicate files, and reports missing indices.

This tool only works on pressure-grid regrids stored in `pgrid_*` folders. It does not merge `regrid_height_<sim>_<idx>.h5` files.

## What It Does

Given a THOR results directory, `pgrid_merge`:

1. Finds all `pgrid_*` folders that contain files named like `regrid_<simulation_id>_<index>.h5`.
2. Determines the full merged index span from the actual files found.
3. Creates or updates a canonical merged folder named like `pgrid_<lowest>_<highest>_<stride>`.
4. If the same output index appears in multiple source folders, keeps the largest file.
5. Reports any missing single files or missing intervals inside the merged coverage.
6. Writes a merge log describing coverage, duplicate decisions, and missing intervals.
7. Optionally deletes redundant source `pgrid_*` folders after a successful merge.

## Why This Is Useful

Pressure regridding is often run in pieces. This can leave behind overlapping folders with many duplicate files. Common reasons include:

- regridding only a short interval before shutting down the machine
- restarting a long regrid later with a larger interval
- testing individual files or short ranges before committing to a full run

As a result, the same results directory may contain several partially redundant `pgrid_*` folders. `pgrid_merge` gives you one cleaner merged target without having to sort those files by hand.

## Where The Tool Lives

- script: [mjolnir/pgrid_merge.py](/home/malkouka/THOR/mjolnir/pgrid_merge.py)
- wrapper: [mjolnir/pgrid_merge](/home/malkouka/THOR/mjolnir/pgrid_merge)

You can run either one.

## Basic Usage

Run a dry run first:

```bash
python3 /home/malkouka/THOR/mjolnir/pgrid_merge.py \
  /home/malkouka/THOR/venus_5_long_results \
  --simulation-id venus \
  --dry-run
```

If the summary looks correct, run the real merge:

```bash
python3 /home/malkouka/THOR/mjolnir/pgrid_merge.py \
  /home/malkouka/THOR/venus_5_long_results \
  --simulation-id venus
```

If you also want to remove redundant old source folders after the merge:

```bash
python3 /home/malkouka/THOR/mjolnir/pgrid_merge.py \
  /home/malkouka/THOR/venus_5_long_results \
  --simulation-id venus \
  --delete-source-folders
```

If you are already inside [mjolnir](/home/malkouka/THOR/mjolnir), you can also use:

```bash
./pgrid_merge /home/malkouka/THOR/venus_5_long_results --simulation-id venus --dry-run
```

## Dry Run

A dry run means the tool performs discovery and planning only.

It will:

- scan source `pgrid_*` folders
- decide the merged target folder name
- resolve duplicate candidates
- detect missing files or missing intervals
- show how many files would be created, replaced, or kept

It will not:

- create the merged target folder
- copy or hardlink any files
- replace smaller duplicates
- delete any source folders

### Important Dry-Run Note

By default, a dry run does not write the normal merge log file. It only prints the summary to the terminal.

If you want a saved preview log during dry run, pass `--log-path` explicitly:

```bash
python3 /home/malkouka/THOR/mjolnir/pgrid_merge.py \
  /home/malkouka/THOR/venus_5_long_results \
  --simulation-id venus \
  --dry-run \
  --log-path /home/malkouka/THOR/venus_5_long_results/pgrid_merge_preview.log
```

## Duplicate Handling

If the same file index appears in multiple source folders, `pgrid_merge` keeps the largest version.

This is based on the assumption that a smaller duplicate may be incomplete or corrupted. The duplicate choice is recorded in the merge log.

Example:

- `pgrid_1000_1020_1/regrid_venus_1010.h5`
- `pgrid_1000_1050_1/regrid_venus_1010.h5`

If both exist, the tool compares file sizes and keeps the larger one.

## Missing Files And Missing Intervals

The tool reports missing coverage based on the actual merged range.

Example:

- if the merged folder covers `1000` through `1050`
- but `1032` is missing

the log reports `1032`.

If several files are missing in a row, the log reports an interval such as:

- `1032-1039`

This helps you quickly see which output files still need pressure regridding.

## Merge Log

A real merge writes a log file into the results directory. The default log name is:

```text
pgrid_merge_<target_folder_name>.log
```

For example:

```text
/home/malkouka/THOR/venus_5_long_results/pgrid_merge_pgrid_0_7061_1.log
```

The log includes:

- source folders that were scanned
- declared and actual folder coverage
- duplicate-resolution choices
- missing merged intervals
- planned or applied file actions
- optional source-folder deletions
- pressure-grid text comparisons when companion `pgrid_*.txt` files exist

## Pressure-Grid Text Files

The tool also looks for companion text files such as:

- `pgrid_1000_1020_1.txt`
- `pgrid_1000_1050_1.txt`

These are compared and summarized in the log.

If a canonical companion text file already exists for the merged target, it is kept as the merged target text.

If no companion text matches the merged target coverage exactly, the tool does not invent a new full-range `pgrid_*.txt` file from a shorter partial one. Instead, it logs that situation so you can decide whether to regenerate a fresh full-range pressure grid later.

This is intentional, because different partial `pgrid_*.txt` files can differ slightly.

## Hardlinks Versus Copies

By default, the merged folder is populated using hardlinks when possible.

This is efficient because:

- it avoids duplicating large HDF5 files unnecessarily
- it is fast
- it uses almost no extra disk space

If hardlinking is not possible, the tool falls back to copying automatically.

If you want to force full copies from the start, use:

```bash
python3 /home/malkouka/THOR/mjolnir/pgrid_merge.py \
  /home/malkouka/THOR/venus_5_long_results \
  --simulation-id venus \
  --copy
```

## Auto-Detecting The Simulation ID

The tool can try to detect the simulation ID automatically from file names such as:

- `regrid_venus_1000.h5`
- `regrid_Earth_54.h5`

If there is more than one simulation ID present in the same results directory, auto-detection becomes ambiguous and the tool will ask you to specify `--simulation-id`.

For Venus runs, it is usually safest to pass:

```bash
--simulation-id venus
```

## Command Reference

### Positional Argument

- `resultsf`
  THOR results directory containing `pgrid_*` folders

### Options

- `-s`, `--simulation-id`
  Simulation ID used in `regrid_<sim>_<idx>.h5`

- `--dry-run`
  Show what would happen without changing files

- `--delete-source-folders`
  Delete redundant source `pgrid_*` folders after a successful real merge

- `--copy`
  Copy files into the merged folder instead of hardlinking them

- `--log-path`
  Custom location for the merge log

- `-h`, `--help`
  Show command help

## Typical Workflow

For a large Venus results directory, a safe workflow is:

1. Run a dry run.
2. Read the terminal summary.
3. If needed, rerun the dry run with `--log-path` to save a preview log.
4. Run the real merge without deleting sources.
5. Inspect the merged folder and merge log.
6. If everything looks correct, rerun with `--delete-source-folders`.

Example:

```bash
python3 /home/malkouka/THOR/mjolnir/pgrid_merge.py \
  /home/malkouka/THOR/venus_5_long_results \
  --simulation-id venus \
  --dry-run
```

Then:

```bash
python3 /home/malkouka/THOR/mjolnir/pgrid_merge.py \
  /home/malkouka/THOR/venus_5_long_results \
  --simulation-id venus
```

Then, after checking the result:

```bash
python3 /home/malkouka/THOR/mjolnir/pgrid_merge.py \
  /home/malkouka/THOR/venus_5_long_results \
  --simulation-id venus \
  --delete-source-folders
```

## Caveats

- This tool does not merge height-coordinate regrids.
- It assumes larger duplicate files are safer than smaller ones.
- It does not generate a fresh full-span pressure-grid text file if only partial companion text files are available.
- It does not regrid missing files for you; it only reports the missing coverage.

## Related Files

- [mjolnir/regrid.py](/home/malkouka/THOR/mjolnir/regrid.py)
- [mjolnir/pgrid.py](/home/malkouka/THOR/mjolnir/pgrid.py)
- [mjolnir/mjolnir.py](/home/malkouka/THOR/mjolnir/mjolnir.py)
