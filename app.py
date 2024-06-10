import html
import json
import os
import os.path
import time

import yt_dlp as youtube_dl
from flask import Flask, request
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from twilio.rest import Client

with open('config.json', 'r') as f:
    config = json.load(f)

account_sid = config['account_sid']
auth_token = config['auth_token']
api_key = config['api_key']
client = Client(account_sid, auth_token)

youtube = build('youtube', 'v3', developerKey=api_key)

output_directory = 'audios/'

app = Flask(__name__)

search_state = None

@app.route('/webhook', methods=['POST'])
def webhook():
    global search_state

    incoming_message = request.values.get('Body', '').lower()
    sender_number = request.values.get('From', '')

    possible_entries = [
        "oi",
        "olá",
        "oii",
        "olá, bot",
        "e ai?",
        "boa tarde",
        "bom dia",
        "boa noite",
        "oi, tudo bem?",
        "olá, como você está?",
        "oi, bot",
        "oi, botmusic",
        "oi, sou novo aqui",
        "oi, preciso de ajuda",
        "olá, estou interessado em música"
    ]

    def send_message(sender_number, message):
        message = client.messages.create(
             from_='whatsapp:+14155238886',
             body=message,
             to=sender_number
        )
        return message.sid

    def send_media(sender_number, file_link, file_id):
        message_body = 'Pronto, aqui está sua música! Se divirta! 😎🔥'
        message = client.messages.create (
            from_='whatsapp:+14155238886',
            body=message_body,
            to=sender_number
        )
        message_media = client.messages.create(
            from_='whatsapp:+14155238886',
            media_url=file_link,
            to=sender_number
        )
        print('Música enviada com sucesso para o usuário.')
        print('Excluindo música do drive!')
        delete_file_from_google(file_id)
        
        global last_interaction_time
        last_interaction_time = time.time()

        periodic_check()
        
        return message.sid, message_media.sid
    
    def authentication():
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json')
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', scopes=["https://www.googleapis.com/auth/drive"]
                )
                creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return creds
    
    def delete_file_from_google(file_id):
        creds = authentication()
        try:
            service = build("drive", 'v3', credentials=creds)
            service.files().delete(fileId=file_id).execute()
            print("Áudio excluído com sucesso do google drive!")
            print("Iniciando contagem de inatividade do usuário!")
        except HttpError as error:
            print(f"Error ao tentar excluir áudio do google drive {error}")

    def upload_audio_to_google_drive(sender_number,audio_file_path):
        creds = authentication()
        try:
            service = build("drive", 'v3', credentials=creds)

            file_meta_data = {
                'name': os.path.basename(audio_file_path),
                'mimeType': 'audio/mpeg'
            }

            media = MediaFileUpload(audio_file_path, mimetype='audio/mpeg', resumable=True)
            file = service.files().create(body=file_meta_data, media_body=media, fields='id').execute()

            service.permissions().create(
                fileId=file['id'],
                body={'role': 'reader', 'type': 'anyone', 'allowFileDiscovery': False}
            ).execute()

            file_id = file.get('id')
            file_link = f'https://drive.google.com/uc?id={file_id}'

            print('Upload do arquivo mp3 concluído com sucesso!')

            send_media(sender_number, file_link, file_id)

            return file_link

        except HttpError as error:
            print(f'Error: {error}')

    def download_music(downloadLink, sender_number, musicName):
        
        request = youtube.search().list(
            q=musicName,
            part='snippet',
            type='video',
            maxResults=1
        )
        response = request.execute()

        if 'items' in response:
            video = response['items'][0]
            title_video = video['snippet']['title']
            title_video = html.unescape(title_video)
            title_video = title_video.replace('?', '').replace('!', '').replace("'", '')

        ydl_opts = {
            'format': 'bestaudio/best',  
            'outtmpl': os.path.join(output_directory, title_video),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',  
                'preferredcodec': 'mp3',  
                'preferredquality': '192',  
        }],
        }
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(downloadLink, download=True)
            audio_file = info_dict['title'].replace('?', '').replace("'", '') + ".mp3"
        upload_audio_to_google_drive(sender_number, os.path.join(output_directory, audio_file))
        return audio_file

    def searchMusic(musicName):
        global search_state

        if search_state is not None:
            if incoming_message in ['SIM', 'sim', 'Sim']:
                send_message(search_state['sender_number'], 'Ok! Estamos baixando a sua música, aguarde... 🤖')
                download_music(search_state['download_link'], search_state['sender_number'], search_state['musicName'])
                search_state = None
                return
            elif incoming_message in ['NÃO', 'não', 'Não']:
                send_message(sender_number, "Entendi. Por favor, diga o nome da música que você deseja baixar: ")
                search_state = None
                return

        request = youtube.search().list(
            q=musicName,
            part='snippet',
            type='video',
            maxResults=1
        )  
        response = request.execute()

        if 'items' in response:
            video = response['items'][0]
            video_id = video['id']['videoId']
            video_link = f'https://www.youtube.com/watch?v={video_id}'
            send_message(sender_number, f"Essa seria a música? {video_link} 😎 \n\nDigite Sim ou Não: ")
            search_state = {'download_link': video_link, 'sender_number': sender_number, 'musicName': musicName}
        else: 
            send_message(sender_number, 'Desculpe. Não encontrei esta música.')

    def check_inative():
        threshold_seconds = 300 # 5 minutos

        current_time = time.time()
        inactive_duration = current_time - last_interaction_time
        
        if inactive_duration > threshold_seconds:
            send_message(sender_number, 'Encerrando o botmusic! Obrigado por usar nossos serviços! 😁'
                         '\nCaso queira baixar mais músicas, é só mandar mensagem novamente! 👇')

    def periodic_check():
        while True:
            check_inative()
            time.sleep(300)
            
    if incoming_message in possible_entries:
        message = ("Olá, eu sou o botmusic, seu botmusic preferido para baixar suas músicas preferidas. 🤖"
                    " \n\nEntão, vamos ao que interessa. Como funciona o bot? É simples, você apenas precisa "
                    "dizer o nome da música, após isso, o bot lhe perguntará se é ela a certa ou não, se não for " 
                    "você poderá tentar de novo. 📃"
                    "\n\nPara continuar a baixar as músicas é só continuar mandando o nome das músicas! 🎶" 
                    "\n\n*Enfim, agora que você já sabe como funciona, me diga o nome da música:* ")
        send_message(sender_number, message)
    elif incoming_message:
        searchMusic(incoming_message)
        # audioFile = download_music(downloadLink)
        # send_audio(sender_number, audioFile)

                
if __name__ == '__main__':
    app.run(debug=True)
