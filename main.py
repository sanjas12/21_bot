import os
import telebot
from dotenv import load_dotenv  # Make sure to install the `python-dotenv` package


class MyBot:

    BOT_TOKEN = os.environ.get("BOT_TOKEN")

    def __init__(self):
        self.bot = telebot.TeleBot(__class__.BOT_TOKEN)

        @self.bot.message_handler(commands=['start', 'hello'])
        def send_welcome(message):
            self.bot.reply_to(message, "Привет, епт, Иру будешь")

        @self.bot.message_handler(func=lambda msg: True)
        def echo_all(message):
            self.bot.reply_to(message, message.text)

        @self.bot.message_handler(commands=['new'])
        def handle_new_command(message):
            self.bot.reply_to(message, "This is a last news from РБK")

        self.bot.infinity_polling()



if __name__ == "__main__":
    my_bot = MyBot()