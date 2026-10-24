from dotenv import load_dotenv
import os
load_dotenv('.env')
print(repr(os.environ.get('CHAT_ID')))
