import qbittorrentapi
import requests
from flask import Flask, request, Response
import subprocess
from payload import disc_embed_payload


DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/938846864906792960/' \
                      'LxZvxAX0R3RHF-K_moQRMYSP8UpSijETXEJk3I1nmvTRA_bPxanCnbGPVF6gKVYuAgY1'


def _connect():
    try:
        qb = qbittorrentapi.Client(
            host='localhost',
            port=8080,
        )
    except Exception as e:
        print('We blew up here!', e)
    return qb


qb = _connect()


def _check_and_start_process():
    call = 'TASKLIST', '/FI', 'imagename eq qbittorrent.exe'
    # use buildin check_output right away
    output = subprocess.check_output(call).decode()
    # check in last line for process name
    last_line = output.strip().split('\r\n')[-1]
    # because Fail message could be translated
    try:
        if last_line.lower().startswith('qbittorrent.exe'.lower()):
            print('Tor is up and running!')
            return True
        else:
            print('Program is not running, starting it now!')
            subprocess.Popen('C:\Program Files\qBittorrent\qbittorrent.exe')
            return True
    except:
        return False


def _get_list_of_all():
    # retrieve and show all torrents
    torrent_list = []
    for tor in qb.torrents_info():
        torrent_list.append(
            {
                "hash": tor["hash"],
                "name": tor["name"],
                "progress": tor["progress"],
                "completed": bool(tor["completed"]),
                "state": tor["state"]
            }
        )
    return torrent_list


def _pause_all_torrents():
    qb.torrents.pause.all()


def _pause_torrent_by_hash(hash):
    qb.torrents.pause(hash)


def _download_file(link):
    qb.torrents_add(link)


def _set_download_location(path):
    qb.set_location(location=path)


def _force_start_all():
    qb.torrents.set_force_start(enable=True, torrent_hashes='all')


def _resume_all():
    qb.torrents.resume(torrent_hashes='all')


def _resume_one(hash):
    qb.torrents.resume(torrent_hashes=hash)


def create_app():
    app = Flask(__name__)
    ip = requests.get('https://api.ipify.org').text
    r = requests.post(DISCORD_WEBHOOK_URL, json={
        "content": f'CURRENT IP: **{str(ip)}**',
    })
    print(r.status_code, ip)

    @app.route('/get-all', methods=['GET'])
    def get_tor_list():
        tor_list = _get_list_of_all()
        for tor in tor_list:
            payload = disc_embed_payload
            embeds = []
            for k,v in tor.items():
                embed_dict = {
                    "name": k.capitalize(),
                    "value": v,
                    "inline": True
                }
                embeds.append(embed_dict)
            payload["embeds"][0]["fields"] = embeds
            r = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        return Response(status=int(r.status_code))

    @app.route('/pause-all', methods=['GET'])
    def pause_all():
        _pause_all_torrents()
        status_code = Response(status=200)
        return status_code

    @app.route('/start', methods=['GET'])
    def start_app():
        _check_and_start_process()
        status_code = Response(status=200)
        return status_code

    @app.route('/connect', methods=['GET'])
    def connect_to_client():
        _connect()
        status_code = Response(status=200)
        return status_code

    @app.route('/pause-one', methods=['GET'])
    def pause_specific():
        args = request.args
        try:
            args.get('hash')
            _pause_torrent_by_hash(hash)
            status_code = Response(status=200)
            return status_code
        except Exception as e:
            print(e)
            status_code = Response(status=400)
            return status_code

    @app.route('/download-link', methods=['POST'])
    def download_file():
        link = request.form["link"]
        _download_file(link)
        status_code = Response(status=200)
        return status_code

    @app.route('/force-start', methods=['GET'])
    def force_start_all_fiels():
        _force_start_all()
        status_code = Response(status=200)
        return status_code

    @app.route('/resume-all', methods=['Get'])
    def resume_all():
        _resume_all()
        status_code = Response(status=200)
        return status_code

    @app.route('/resume-one', methods=['Get'])
    def resume_one():
        args = request.args
        try:
            args.get('hash')
            _resume_one(hash)
            status_code = Response(status=200)
            return status_code
        except Exception as e:
            print(e)
            status_code = Response(status=400)
            return status_code

    return app
