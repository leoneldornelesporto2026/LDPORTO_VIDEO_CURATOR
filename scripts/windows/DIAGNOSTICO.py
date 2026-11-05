import shutil,subprocess,sys
print('Python:',sys.version)
for x in ['ffmpeg','ffprobe','yt-dlp','ollama']:
    print(f'{x}:',shutil.which(x) or 'NAO ENCONTRADO')
if shutil.which('ffmpeg'):
    p=subprocess.run(['ffmpeg','-hide_banner','-encoders'],capture_output=True,text=True)
    print('h264_nvenc:', 'SIM' if 'h264_nvenc' in p.stdout+p.stderr else 'NAO')
