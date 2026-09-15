#!/bin/bash
#SBATCH -A nr_venth
#SBATCH --job-name=plot_venus_uv
#SBATCH --partition=test
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32000
#SBATCH --time=01:00:00
#SBATCH --output=plot_venus_uv_%j.out
#SBATCH --error=plot_venus_uv_%j.err

set -e

MJOLNIR_DIR=/scratch/nr_venth/thor/mjolnir_mod
RESULTS=/home/nr_vecm/nr_venth_scratch/thor/THOR/venus_results
PYENV=/scratch/nr_venth/thor/THOR/thor_py

cd "$MJOLNIR_DIR"

module purge
module load cray-python/3.11.7
module load cuda/12.3

export LD_LIBRARY_PATH=/opt/software/packages/cuda/12.3/lib64:$LD_LIBRARY_PATH
export MPLBACKEND=Agg

source "$PYENV/bin/activate"
export PATH="$PYENV/bin:$PATH"
hash -r

echo "Plotting Venus THOR output 24800 to 25000"
echo "Node:"
hostname
echo "GPU:"
nvidia-smi
echo "Python:"
which python3
python3 --version
echo "Mjolnir dir: $MJOLNIR_DIR"
echo "Results dir: $RESULTS"
echo "Start:"
date

echo "Checking input files..."
ls -lh "$RESULTS"/esp_output_venus_24800.h5
ls -lh "$RESULTS"/esp_output_venus_25000.h5

echo "Plot 1: uver pressure"
python3 mjolnir.py uver -vc pressure -f "$RESULTS" -i 24800 -l 25000

echo "Plot 2: uver height"
python3 mjolnir.py uver -vc height -f "$RESULTS" -i 24800 -l 25000

echo "Plot 3: vver pressure"
python3 mjolnir.py vver -vc pressure -f "$RESULTS" -i 24800 -l 25000

echo "Plot 4: vver height"
python3 mjolnir.py vver -vc height -f "$RESULTS" -i 24800 -l 25000

echo "Finished:"
date
