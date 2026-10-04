# Contributing to Swarm-Lite

Thank you for your interest in contributing to `swarm-lite`!

## Development Guidelines

1. **Pure Standard Library Core**: `swarm-lite` core code must have **zero external runtime dependencies**. Use standard Python library modules only.
2. **Token Economy**: All worker orchestrations must honor the token quota ceiling (\(\le 1500\) tokens/worker).
3. **Test Coverage**: All bug fixes and new features must be accompanied by comprehensive unit tests under `tests/`.

## Workflow

1. Fork the repository on GitHub.
2. Create a feature branch (`git checkout -b feature/my-feature`).
3. Run unit tests locally (`python3 -m unittest discover -s tests`).
4. Commit your changes with clear commit messages.
5. Push to your branch and open a Pull Request.

## Code Style

Follow PEP 8 standard formatting and type hints.
