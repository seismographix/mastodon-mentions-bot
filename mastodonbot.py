"""
Mastodon Mentions Bot

This module implements a Mastodon bot that can automatically respond to mentions.
The bot is designed to run as a daemon process, which can be started, stopped, 
and checked for its status.

The bot uses the Mastodon API library to access the Mastodon API and the 
Apprise library to send notifications to the administrator of the bot.

The bot also supports plugins that can process mentions in customized ways. The 
plugins must be located in the 'plugins' folder and implement the 
MastodonBotPlugin interface. See example plugin: plugins/example_plugin.py

Environment variables that are used by the Mastodon bot:
- MASTODON_BASE_URL: the base URL of the Mastodon instance
- MASTODON_ACCESS_TOKEN: the access token for the bot account 
- APPRISE_SERVICE_URL: the Apprise service URL for sending notifications to the 
    administrator of the bot
"""

import atexit
import os
import logging
from logging.handlers import RotatingFileHandler
import mastodon
import time
import sys
import signal
from dotenv import load_dotenv
from apprise import Apprise
from threading import Thread
from queue import Queue
from pathlib import Path
import importlib.util
import fire


class NotifierError(Exception):
    pass


class Notifier:
    """
    Class for sending notifications to the administrator of the Mastodon bot.

    The Notifier uses the Apprise library to send notifications to the 
    administrator of the bot.
    By using the Apprise library, the Notifier can be configured for such 
    notification services like Email, Mastodon, Telegram, Signal, etc.
    Configuration of the Notifier is done by the environment variable 
    APPRISE_SERVICE_URL. The supported configurations with their service URLs 
    are listed here: https://github.com/caronc/apprise#supported-notifications
    """

    def __init__(self, url):
        """
        Initializes the Notifier object with the specified service URL.
        """
        self.apprise = Apprise()
        self.apprise.add(url)

    def send(self, msg):
        """
        Sends a notification to the administrator of the Mastodon bot.
        """
        result = self.apprise.notify(body=msg)
        if result is None:
            raise NotifierError("No Apprise configuration available for "
                                f"message: {msg}")
        elif not result:
            raise NotifierError(f"""Sending notification failed. 
-> Apprise url: {self.apprise.urls(privacy=True)} 
-> Message: {msg}""")


class MastodonMentionListener(mastodon.StreamListener):
    """
    Listens for mentions in the Mastodon stream.

    This class is a custom listener for the Mastodon stream that processes new 
    notifications. It is used by the MastodonBot class to listen for new 
    mentions.
    """

    def __init__(self, client, plugins, logger):
        """
        Initializes the MastodonMentionListener object with the specified 
        client and plugins.
        """
        self.client = client
        self.plugins = plugins
        self.logger = logger

    def on_notification(self, notification):
        """
        Processes new notifications.

        This method is called whenever a new notification is received from the 
        Mastodon stream. It checks if the notification is a mention and, if so, 
        processes it with the plugins.
        """
        if notification["type"] == "mention":
            self.logger.info('New mention: %s',
                             notification['status']['content'])
            return notification


class MastodonBot:
    """
    Class for the Mastodon bot.

    The MastodonBot class is responsible for starting and stopping the Mastodon 
    bot, as well as for processing mentions and sending notifications to the 
    bot administrator. The MastodonBot class uses the Mastodon library for 
    interacting with the Mastodon API, and the PluginLoader class for loading 
    and managing plugins from the 'plugins' directory to process mentions.  
    """
    
    PIDFILE = Path.home() / '.mastodonbot.pid'

    def __init__(self, mastodon_url, mastodon_token, apprise_url):
        """
        Initializes the MastodonBot object.
        """
        self.logger = self._get_logger()
        self.client = mastodon.Mastodon(access_token=mastodon_token,
                                        api_base_url=mastodon_url)
        self.notifier = Notifier(apprise_url)
        self.plugin_loader = PluginLoader(self.logger)
        self.plugins = None
        self.mention_queue = Queue()
        self.mention_thread = Thread(target=self._process_mentions,
                                     args=(self.mention_queue,))
        self.stream_thread = None

    def _get_logger(self):

        logger = logging.getLogger('Mastodon Bot')
        logger.setLevel(logging.DEBUG)
    
        # Create console handler with custom formatting
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter("%(levelname)s: %(message)s")
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # Create file handler with custom formatting and rotating file handler
        file_handler = RotatingFileHandler(filename="mastodonbot.log",
                                           maxBytes=1000000, backupCount=3)
        file_formatter = logging.Formatter("%(asctime)s - %(name)s - "
                                           "%(levelname)s - %(message)s")
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        return logger

    def get_pid(self):
        pid = int(self.PIDFILE.read_text())
        return pid

    def _remove_pidfile(self):
        self.PIDFILE.unlink(missing_ok=True)

    def start(self):
        """
        Starts the Mastodon bot.
        """
        
        if self.is_running():
            self.logger.info("Mastodon bot is already running with PID %s",
                             self.get_pid())
            return
        
        self.logger.info("Mastodon bot is starting")

        # fork the process and detach from terminal
        try:
            pid = os.fork()
            if pid > 0:
                signal.signal(signal.SIGTERM, self._stop)
                sys.exit(0)
        except OSError as e:
            self.logger.exception("Forking the Mastodon bot failed: %s", e)
            sys.exit(1)

        os.chdir("/")
        os.setsid()
        os.umask(0)

        # write PID to file
        self.PIDFILE.write_text(str(os.getpid()))

        # register exit function to remove PID file
        atexit.register(self._remove_pidfile)

        # Load plugins 
        self.plugins = self.plugin_loader.load_plugins(self.client)
        
        # Start thread for processing mentions
        self.mention_thread.start()
        
        # Start stream for mentions
        try:
            self.stream_thread = Thread(target=self._stream_mentions)
            self.stream_thread.start()
        except Exception as e:
            self.logger.error('Error starting stream: %s', e)

        self.logger.info("Mastodon bot is running with PID %s", self.get_pid())

    def _stream_mentions(self):
        """
        Streams mentions and adds them to the queue.
        """
        listener = self._create_listener()
        for mention in self._stream_mentions_from_listener(listener):
            if not self.is_running:
                break
            self._add_mention_to_queue(mention)

    def _create_listener(self):
        """
        Creates a listener object for streaming mentions.
        """
        listener = MastodonMentionListener(self.client, self.plugins, self.logger)
        return listener

    def _stream_mentions_from_listener(self, listener):
        """
        Streams mentions from the Mastodon API using the specified listener object.
        """
        while self.is_running:
            try:
                for mention in self.client.stream_user(listener):
                    yield mention
            except mastodon.MastodonNetworkError as e:
                self.logger.error('Error in stream: %s', e)
                self.logger.info("Reconnecting in 10 seconds...")
                time.sleep(10)
                continue
            except Exception as e:
                self.logger.error('Error in stream: %s', e)
                self.notifier.send("Mastodon Mentions Bot. Error in stream: "
                                   f"{e}")
                break
        
        self.logger.info("Stream thread has ended")
    
    def _add_mention_to_queue(self, mention):
        """
        Adds a mention to the queue for processing.
        """
        self.logger.info('New mention: %s', mention['content'])
        self.mention_queue.put(mention)

    def _process_mentions(self, queue):
        """
        Processes mentions from the queue.
        """
        while self.is_running:
            mention = queue.get()
            if mention is None:
                break
            self._process_mention(mention)

        self.logger.info("Mention processing thread has ended")

    def _process_mention(self, mention):
        """
        Processes a single mention.
        """
        self.logger.info('New mention: %s', mention['content'])
        for plugin in self.plugins:
            self._process_mention_with_plugin(mention, plugin)

        # Reload plugins to check availability
        self.plugins = self.plugin_loader.load_plugins(self.client)
        
    def _process_mention_with_plugin(self, mention, plugin):
        """
        Processes a single mention with a specific plugin.
        """
        try:
            if plugin.is_available:
                plugin.process_mention(mention)
            else:
                self.logger.warning('Plugin %s is currently unavailable.',
                                    type(plugin).__name__)
        except mastodon.MastodonNetworkError:
            plugin.is_available = False
            self.logger.error('Error in plugin %s: Mastodon instance is '
                              'currently unavailable.', type(plugin).__name__)
        except Exception as e:
            self.logger.error('Error in plugin %s: %s', type(plugin).__name__,
                              e)

    def _stop(self):
        """
        Stops the Mastodon bot.
        """
            
        if self.is_running():
            
            msg = "Mastodon bot is being stopped"
            self.logger.info(msg)
            self.notifier.send(msg)
        
            # Stop processing mentions
            self.mention_queue.put(None)
            self.mention_thread.join()
            
            # Stop streaming mentions
            if self.stream_thread is not None:
                self.client.stream_stop()
                self.stream_thread.join()

            msg = "Mastodon bot has been stopped"
            self.logger.info(msg)
            self.notifier.send(msg)

            self._remove_pidfile()
        
        else:
            self.logger.info("Mastodon bot is not running")
            return

    def is_running(self):
        """
        Check if the Mastodon bot is running.
        """
        
        if self.PIDFILE.exists():

            pid = self.get_pid()
            if not pid:
                return False

            # Try sending a signal 0 to the daemon process
            try:
                os.kill(pid, 0)
            except OSError:
                # PID file exists, but the process is not running
                self._remove_pidfile()  # Clean up the PID file
                return False
            else:
                return True


class PluginLoader:
    """
    Class for loading the plugins of the Mastodon bot.
    
    See example_plugin.py in the the 'plugins' directory for how to process 
    Mastodon posts which mentioned the bot account.  
    """

    def __init__(self, logger):
        self.logger = logger 

    def load_plugins(self, client):
        """
        Loads all plugins from the 'plugins' directory
        """
        plugin_folder = self._get_plugin_folder()
        plugins = []
        for file_path in plugin_folder.glob('*.py'):
            if file_path.stem.startswith("_"):
                continue
            plugin = self._load_plugin(file_path, client)
            if plugin:
                plugins.append(plugin)
                self.logger.info('Append plugin: %s', file_path.name)
        self.logger.info('%s plugin(s) loaded', len(plugins))
        return plugins
    
    def _get_plugin_folder(self):
        """
        Returns the path to the plugin folder
        """
        script_path = Path(__file__).resolve()
        plugin_folder = script_path.parent / "plugins"
        return plugin_folder
    
    def _load_plugin(self, file_path, client):
        """
        Loads a plugin from a Python file
        """
        module_name = file_path.stem
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "MastodonBotPlugin"):
            self.logger.warning('MastodonBotPlugin class not found in %s',
                                file_path)
            return None
        return module.MastodonBotPlugin(client)


def start():
    bot.start()
    return "Mastodon bot is started"

    
def restart():
    stop()
    time.sleep(1)
    start()
    return "Mastodon bot is restarted."


def status():
    if bot.is_running():
        return "Mastodon bot is running."
    else:
        return "Mastodon bot is not running."


def stop():
    if bot.is_running():
        pid = bot.get_pid()
        os.kill(pid, signal.SIGTERM)
    return "Mastodon bot is stopped"


def testnotify():
    try:
        bot.notifier.send('Test notification from the Mastodon Mentions Bot')
    except Exception as e:
        return str(e)
    return "Success. Please check your incoming notifications."


if __name__ == "__main__":
        
    load_dotenv()
    
    def get_env_variable(name):
        value = os.getenv(name)
        if not value:
            raise ValueError(f"The {name} environment variable is not set. "
                             f"Please set it before running the bot.")
        return value

    MASTODON_BASE_URL = get_env_variable("MASTODON_BASE_URL")
    MASTODON_ACCESS_TOKEN = get_env_variable("MASTODON_ACCESS_TOKEN")
    APPRISE_SERVICE_URL = get_env_variable("APPRISE_SERVICE_URL")

    bot = MastodonBot(MASTODON_BASE_URL, MASTODON_ACCESS_TOKEN,
                      APPRISE_SERVICE_URL)
  
    fire.Fire({
        'start': start,
        'restart': restart,
        'stop': stop,
        'status': status,
        'testnotify': testnotify
        })

