import qbittorrentapi
import requests
import os
import boto3
import subprocess
import yaml
import re
import shutil
import json


# get values from the yaml file
with open('config.yaml', 'r') as file:
    cfg = yaml.safe_load(file)


MOVIES_DIR = 'MOVIE'
TV_DIR = 'TV'

def connect():
    try:
        qb = qbittorrentapi.Client(
            host=cfg["qb"]["host"],
            port=cfg["qb"]["port"],
        )
    except Exception as e:
        print('We blew up here!', e)
    return qb


def retrieve_command_from_sqs(queue):
    response = queue.receive_messages(
        QueueUrl=cfg["plex"]["sqs_queue"],
        AttributeNames=['ALL'],
        MaxNumberOfMessages=1,
        VisibilityTimeout=5,
        WaitTimeSeconds=5,
        MessageAttributeNames=['ALL']
    )
    return response


def check_and_start_process():
    call = 'TASKLIST', '/FI', f'imagename eq {cfg["qb"]["process"]}'
    # use buildin check_output right away
    output = subprocess.check_output(call).decode()
    # check in last line for process name
    last_line = output.strip().split('\r\n')[-1]
    # because Fail message could be translated
    try:
        if last_line.lower().startswith(f'{cfg["qb"]["process"]}'.lower()):
            print('Tor is up and running!')
            return True
        else:
            print('Program is not running, starting it now!')
            subprocess.Popen(f'C:\\Program Files\\{cfg["qb"]["process"].split(".")[0]}\\{cfg["qb"]["process"]}')
            return True
    except:
        return False


def parse_message_body(message_body:dict):
    command = message_body["command"].lower()
    data = message_body["data"]
    try:
        if 'get-all' == command:
            get_tor_list()
        if 'pause-all' == command:
            _pause_all()
        if 'pause-one' == command:
            _pause_torrent_by_hash(data)
        if 'start' == command:
            check_and_start_process()
        if 'connect' == command:
            connect()
        if 'download-link' == command:
            _download_file(data)
        if 'force-start' == command:
            _force_start_all()
        if 'resume-all' == command:
            _resume_all()
        if 'resume-one' == command:
            _resume_one(data)
        if 'delete-one' == command:
            _delete_file(data)
        if 'tag-tv' == command:
            _tag_tv(data)
        if 'tag-movie' == command:
            _tag_movie(data)
        if 'process-file' == command:
            _process_file(data)
    except Exception as e:
        payload = {"content": f'Error running command: {command}\n{e}'}
        r = requests.post(cfg["discord"]["url"], json=payload)
        print(r.status_code, r.text)


def _process_file(hash):
    DL_DIR = cfg["disk"]["dl_path"]
    movie_dir = cfg["disk"]["movie_path"]
    tv_dir = cfg["disk"]["tv_path"]
    try:
        tor = _get_file_by_hash(hash)[0]
        name = tor["name"]
        tag = tor["tags"]
        stuff = re.compile(r'.+?(?=\d{4})\d{4}|.+\S.\d{1,3}p.*')

        for movie in os.listdir(DL_DIR):
            # only rename files that have been tagged so we know where to put them
            if str(movie) == name and tag != "":
                try:
                    movie_name = stuff.search(movie).group()
                    if movie_name is not None:
                        new_file = DL_DIR + ' '.join(movie_name.split('.'))
                        os.rename(DL_DIR + movie, new_file)
                        for file in os.listdir(new_file):
                            # move subtitles out to the parent folder
                            if 'subs' in file.lower():
                                sub_dir = new_file + '\\' + file
                                for sub in os.listdir(sub_dir):
                                    os.rename(sub_dir + '\\' + sub, new_file + '\\' + sub)
                                os.rmdir(sub_dir)
                            if 'RARBG' in str(file):
                                if file.endswith('.exe') or file.endswith('.txt'):
                                    os.remove(new_file + f'/{file}')
                            if file.endswith('nfo'):
                                os.remove(new_file + f'/{file}')
                        # now move it to the new location
                        if tag == 'movie':
                            new_path = movie_dir
                            shutil.move(new_file, new_path)
                        elif tag == 'tv':
                            new_path = tv_dir
                            shutil.move(new_file, new_path)

                except Exception as e:
                    print(e)
                    continue
    except Exception as e:
        return e


def _get_file_by_hash(hash):
    return qb.torrents_info(torrent_hashes=hash)


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
                "state": tor["state"],
                "amount_left": tor["amount_left"],
                "tags": tor["tags"]
            }
        )
        if tor.state_enum.is_complete and not tor.state_enum.is_paused:
            _pause_torrent_by_hash(tor["hash"])
    return torrent_list


def _pause_all():
    return qb.torrents.pause.all()


def _pause_torrent_by_hash(hash):
    return qb.torrents.pause(hash)


def _download_file(link):
    return qb.torrents_add(link)


def _tag_tv(hash):
    return qb.torrents_add_tags(tags='tv', torrent_hashes=hash)


def _tag_movie(hash):
    return qb.torrents_add_tags(tags='movie', torrent_hashes=hash)


def _delete_file(hash, delete_files=True):
    return qb.torrents_delete(delete_files=delete_files,torrent_hashes=hash)


def _set_download_location(path):
    return qb.set_location(location=path)


def _force_start_all():
    return qb.torrents.set_force_start(enable=True, torrent_hashes='all')


def _resume_all():
    return qb.torrents.resume(torrent_hashes='all')


def _resume_one(hash):
    return qb.torrents.resume(torrent_hashes=hash)


def get_tor_list():
    tor_list = _get_list_of_all()
    formatted_message = []
    for tor in tor_list:
        formatted_message.append(
            f'**Hash**: {tor["hash"]}\n**Name**: {tor["name"].capitalize()}\n**Completed**: {tor["completed"]}\n'
            f'**State**: {tor["state"]}\n**Left to DL**: {tor["amount_left"]}\n**Tags**: {tor["tags"]}\n'
        )
    payload = {
        "content": "\n".join(formatted_message)
    }
    r = requests.post(cfg["discord"]["url"], json=payload)
    print(r.status_code)


def post_status_change(tor:dict):
    payload = {
        "content": "**Status Change!**\n"
        f'**Hash**: {tor["hash"]}\n**Name**: {tor["name"].capitalize()}\n**Completed**: {tor["completed"]}\n'
        f'**State**: {tor["state"]}\n**Left to DL**: {tor["amount_left"]}\n**Tags**: {tor["tags"]}\n'
    }
    r = requests.post(cfg["discord"]["url"], json=payload)
    print(r.status_code)


if __name__ == '__main__':
    files_to_be_processed = []
    # Instantiate everything we need
    # start the application
    check_and_start_process()
    # connect to the process
    qb = connect()
    # create our sqs object
    sqs = boto3.resource(
        'sqs',
        region_name=cfg["plex"]["region"],
        aws_access_key_id=cfg["plex"]["aws_key_id"],
        aws_secret_access_key=cfg["plex"]["aws_secret_id"]
    )
    # grab the queue object
    queue = sqs.get_queue_by_name(QueueName=cfg["plex"]["queue_name"])

    #start the polling loop
    current_tors = _get_list_of_all()
    while True:
        messages_to_delete = []
        # check for new messages
        response = retrieve_command_from_sqs(queue)
        # if we have a response
        for message in response:
            # parse the response of message.body here
            body = json.loads(message.body)
            parse_message_body(body)

            messages_to_delete.append({
                'Id': message.message_id,
                'ReceiptHandle': message.receipt_handle
            })
            # if you don't receive any notifications the
            # messages_to_delete list will be empty
            if len(messages_to_delete) == 0:
                break
            # delete messages to remove them from SQS queue
            # handle any errors
            else:
                delete_response = queue.delete_messages(
                    Entries=messages_to_delete)

        for latest_status in _get_list_of_all():
            for tor in current_tors:
                if latest_status in current_tors:
                    # if they match
                    if latest_status["name"] == tor["name"]:
                        # cehck to see if it is finished
                        if latest_status["state"] != tor["state"]:
                            # post to discord about a status change and update the current_tors state
                            tor["state"] = latest_status["state"]
                            post_status_change(latest_status)
                    else:
                        continue
                else:
                    current_tors.append(latest_status)