# FixThisChris (Under Development)

FixThisChris is a GitHub bot designed to swiftly address issues and pull requests (PRs) by generating intelligent responses. By leveraging this bot, you can automate the preliminary troubleshooting and resolution suggestions, thus speeding up the project maintenance process.

## Usage

1. Invite `@fixThisChris` as a contributor to your repository.
2. Mention `@fixThisChris` in the comments of any issue you need assistance with.

## Setup for Contributors

Ensure you have a `.bashrc` or `.zshrc` file in your system, then append the following lines with your credentials:

```bash
export OPENAI_API_KEY="<OPENAI_API_KEY>"
export GITHUB_ACCESS_TOKEN="<GITHUB_ACCESS_TOKEN>"
```

Now, you're ready to run the bot:

```bash
python main.py
```

## Community

Join our [Community Discord](https://discord.gg/ZtRwXYjyrz) for questions, feedback, or just to chat with fellow users and contributors.

## Credits

- Inspired by Repo-Chat created by [mckaywrigley](https://github.com/mckaywrigley)

## Contributing

We welcome contributions from the community! If you have suggestions for improvements or bug fixes, feel free to open an issue or submit a PR. Make sure to check the [Contributing Guidelines](CONTRIBUTING.md) before starting your work.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
