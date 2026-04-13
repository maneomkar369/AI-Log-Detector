# Contributing to Behavioral Log Anomaly Detector

We welcome contributions! Here's how to get started.

## Development Setup

1. **Fork** the repository and clone your fork.
2. Create a Python virtual environment:
   ```bash
   cd edge_server
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and adjust values.
4. Run tests: `pytest tests/ -v`

## Pull Request Process

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Write tests for any new functionality.
3. Ensure all tests pass: `pytest tests/ -v`
4. Commit with clear messages: `git commit -m 'Add feature X'`
5. Push and open a Pull Request.

## Code Style

- **Python**: Follow PEP 8. Use type hints.
- **Kotlin**: Follow official Kotlin style guide.
- **Commits**: Use conventional commit messages.

## Reporting Issues

- Use GitHub Issues with a clear description.
- Include logs, stack traces, and steps to reproduce.
- For security vulnerabilities, email security@yourdomain.com directly.
