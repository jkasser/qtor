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

movie_reg = re.compile(r'.+?(?=\d{4})\d{4}|.+\S.\d{1,3}p.*')
tv_show_reg = re.compile(r'(?<=\.)S\d{1,2}E\d{1,2}|\d{1,2}of\d{1,2}')

FILE_EXTENSIONS = ('avi', 'mp4', 'mkv', 'srt')


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


def delete_extraneous_files(media_path):
    for sub_file in os.listdir(media_path):
        if os.path.isfile(media_path + sub_file) and not sub_file.endswith(FILE_EXTENSIONS):
            # delete all the crap that gets left in these directories except for the file itself
            os.remove(media_path + sub_file)


def get_name_for_subs(media_path):
    for sub_file in os.listdir(media_path):
        if sub_file.endswith(FILE_EXTENSIONS):
            # grab everything but it's extension
            media_name = '.'.join(sub_file.split('.')[:-1])
            rename_and_move_subs(media_path, media_name)


def rename_and_move_subs(media_path, media_name):
    for sub_file in os.listdir(media_path):
        if os.path.isdir(media_path + sub_file) and 'subs' == sub_file.lower():
            for sub in os.listdir(media_path + sub_file):
                # sometimes subtitles are individual files
                if os.path.isfile(media_path + sub_file + '\\' + sub):
                    # rename the subs here
                    # rules are
                    # 4 - forced (foreign languages)
                    # 3 - for deaf people (with sounds i.e. "*sigh*")
                    # 2 - normal subtitles
                    # if there is one with _2 in the name, this is all we need, rename it and bail
                    if '3_English' in sub:
                        ext = '.en.cc.ext'
                    elif '4_English' in sub.lower():
                        ext = '.en.forced.ext'
                    elif 'English' in sub.lower():
                        ext = '.en.srt'
                    else:
                        continue
                    try:
                        os.rename(media_path + sub_file + '\\' + sub, media_path + media_name + ext)
                    except OSError:
                        continue
                #other times, like tv shows there are sub folders in the subs directory
                elif os.path.isdir(media_path + sub_file + '\\' + sub):
                    for sub_folder_file in os.listdir(media_path + sub_file + '\\' + sub):
                        if '3_English' in sub_folder_file:
                            ext = '.en.cc.ext'
                        elif '4_English' in sub_folder_file:
                            ext = '.en.forced.ext'
                        elif 'English' in sub_folder_file:
                            ext = '.en.srt'
                        else:
                            continue
                        try:
                            os.rename(media_path + sub_file + '\\' + sub + '\\' + sub_folder_file, media_path + sub + ext)
                        except OSError:
                            continue


def _process_file(hash):
    DL_DIR = cfg["disk"]["dl_path"]
    movie_dir = cfg["disk"]["movie_path"]
    tv_dir = cfg["disk"]["tv_path"]
    try:
        tor = _get_file_by_hash(hash)[0]
        name = tor["name"]
        tag = tor["tags"]

        for movie in os.listdir(DL_DIR):
            # only rename files that have been tagged so we know where to put them
            if str(movie) == name and tag != "":
                try:
                    if os.path.isdir(DL_DIR + movie):
                        if re.search(tv_show_reg, movie) is not None:
                            # rename the new folder
                            new_name = ' '.join(movie.split('.')[:-2])
                            os.rename(DL_DIR + movie, DL_DIR + new_name)

                        if re.search(movie_reg, movie) is not None:
                            # rename the new folder
                            new_name = re.search(r'.+(?=\.1080p)', movie).group().replace('.', ' ')
                            os.rename(DL_DIR + movie, DL_DIR + new_name)

                        sub_dir = DL_DIR + new_name + '\\'
                        delete_extraneous_files(sub_dir)
                        get_name_for_subs(sub_dir)
                    # now move it to the new location
                    if tag == 'movie':
                        new_path = movie_dir
                        shutil.move(DL_DIR+new_name, new_path)
                    elif tag == 'tv':
                        new_path = tv_dir
                        shutil.move(DL_DIR+new_name, new_path)
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

    # start the polling loop
    while True:
        current_tors = _get_list_of_all()
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
                        # check to see if it is finished
                        if latest_status["state"] != tor["state"]:
                            # post to discord about a status change and update the current_tors state
                            tor["state"] = latest_status["state"]
                            post_status_change(latest_status)
                            # stop the spam and break out so we can re-declare latest_status
                            break
                    else:
                        continue
                else:
                    current_tors.append(latest_status)
