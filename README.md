# Mastodon Mentions Bot

This module implements a Mastodon Bot that can automatically respond to 
mentions. The bot is designed to run as a daemon process, which can be started,
stopped and checked for its status.

The bot uses the Mastodon API library to access Mastodon. Problems are reported 
to the administrator of the bot via the Apprise library. 
The Apprise library supports several notification services like Email,
Mastodon, Telegram, Signal, etc.
See all supported services here: https://github.com/caronc/apprise#supported-notifications

The bot uses plugins to process mentions in customized ways. The plugins
must be located in the `plugins` folder and implement the MastodonBotPlugin 
interface. 


Notes:
- Only tested on Linux.
- Tested manually. You may know, what it means. ;)

## Installation

1. Clone the repository
2. Install the required packages: `pip install -r requirements.txt`
   		
## Usage

1. Copy the example: `cp env.example .env`. Customize the environment variables in 
   the new .env file:
   - `MASTODON_BASE_URL`: the base URL of the Mastodon instance
   - `MASTODON_ACCESS_TOKEN`: the access token for the Mastodon bot account
   - `APPRISE_SERVICE_URL`: the Apprise service URL for sending notifications to 
   		the bot administrator.
2. Start the bot with `python mastodonbot.py start`
3. Check the status of the bot with `python mastodonbot.py status`
4. Send a test notification to the bot administrator with `python mastodonbot.py testnotify`.
   - `APPRISE_SERVICE_URL` must be configured. 
   - Example: `mastodons://<TOKEN>@<xyy.social>/?visibility=direct`
   - Other options: https://github.com/caronc/apprise#supported-notifications
6. To test the out-of-the-box `example_plugin.py`, say `hello` to the bot account and
   the bot will greet back. The account mentioning the bot must not the bot account
   itself.
6. Copy `./plugins/example_plugin.py` and adapt the method `process_mention` of the 
   new plugin to your liking.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file
for details.
