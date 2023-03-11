"""
Mastodon Bot plugin

This module shows the MastodonBotPlugin interface, which a plugin for the 
Mastodon Bot must implement.
The interface consists of the 'is_available' and 'process_mention' methods.

The 'is_available' method is used to check if the plugin is currently available.
If the plugin is not available, it will be skipped when processing mentions.

The 'process_mention' method is called for each mention that the Mastodon Bot 
receives. The method takes the mention object as an argument and can perform 
any processing on the mention that is desired. 

"""

import mastodon

class MastodonBotPlugin:
    """Example Mastodon bot plugin.

    This example plugin processes mentions with 'hello' in the status text and 
    and sends a greetings back. 
    """

    def __init__(self, client):
        self.client = client

    @property
    def is_available(self):
        """
        Checks if the plugin is currently available.
        """
        try:
            self.client.account_verify_credentials()
            return True
        except mastodon.MastodonNetworkError:
            return False

    def process_mention(self, mention):
        """
        Processes a mention and replies with a message.
        """
        if not self.is_available:
            return
        if "hello" in mention['status']['content'].lower():
            message = f"Hello @{mention['account']['acct']}."
            self.client.status_post(message, 
                                    in_reply_to_id=mention["status"]["id"],
                                    visibility='direct')

