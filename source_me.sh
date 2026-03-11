set | grep -q '^BASH_VERSION=' || echo "use bash for your shell"
set | grep -q '^BASH_VERSION=' || exit 1

# Set Python environment optimizations
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

source ~/.bashrc

# add emwy_tools/ to PYTHONPATH so shared modules are importable
export PYTHONPATH="${PYTHONPATH}:$(git rev-parse --show-toplevel)/emwy_tools"
