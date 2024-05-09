import qbittorrentapi
import requests
import os
import boto3
import subprocess
import yaml
import re
import shutil
import json
import datetime
import logging
from logging.handlers import RotatingFileHandler


log_file = os.path.expandvars("%USERPROFILE%\\Desktop\\qtor.log")
logger = logging.getLogger('QTOR')
handler = RotatingFileHandler(log_file, maxBytes=1024**2, backupCount=2)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


# get values from the yaml file
def get_config():
    with open('config.yaml', 'r') as file:
        cfg = yaml.safe_load(file)
    return cfg

# names of the folders we will move files to
MOVIES_DIR = 'MOVIE'
TV_DIR = 'TV'

# file extensions we won't delete
FILE_EXTENSIONS = ('avi', 'mp4', 'mkv', 'srt')

# how we keep track which tors we have processed for alerting purposes
processed_tors = {}


def connect(cfg):
    try:
        qb = qbittorrentapi.Client(
            host=cfg["qb"]["host"],
            port=cfg["qb"]["port"],
        )
    except Exception as e:
        logger.error('We blew up here!', e)
    return qb


def retrieve_command_from_sqs(cfg, queue):
    response = queue.receive_messages(
        QueueUrl=cfg["plex"]["sqs_queue"],
        AttributeNames=['ALL'],
        MaxNumberOfMessages=1,
        VisibilityTimeout=30,
        WaitTimeSeconds=5,
        MessageAttributeNames=['ALL']
    )
    return response


def check_and_start_process(cfg):
    call = 'TASKLIST', '/FI', f'imagename eq {cfg["qb"]["process"]}'
    # use buildin check_output right away
    output = subprocess.check_output(call).decode()
    # check in last line for process name
    last_line = output.strip().split('\r\n')[-1]
    # because Fail message could be translated
    try:
        if last_line.lower().startswith(f'{cfg["qb"]["process"]}'.lower()):
            logger.info('Tor is up and running!')
            return True
        else:
            logger.info('Program is not running, starting it now!')
            subprocess.Popen(f'C:\\Program Files\\{cfg["qb"]["process"].split(".")[0]}\\{cfg["qb"]["process"]}')
            return True
    except:
        return False


def parse_message_body(cfg, message_body: dict):
    command = message_body["command"].lower()
    data = message_body["data"]
    logger.info(f"Received command: {command}")
    try:
        if 'get-all' == command:
            get_tor_list(cfg)
        if 'pause-all' == command:
            _pause_all()
        if 'pause-one' == command:
            _pause_torrent_by_hash(data)
        if 'start' == command:
            check_and_start_process(cfg)
        if 'connect' == command:
            connect(cfg)
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
            _process_file(cfg, data)
        if 'get-logs' == command:
            _send_logs(cfg)
    except Exception as e:
        payload = {"content": f'Error running command: {command}\n{e}'}
        r = requests.post(cfg["discord"]["url"], json=payload)
        logger.error("Error processing command.", r.status_code, r.text)


def delete_extraneous_files(media_path):
    count = 0
    for sub_file in os.listdir(media_path):
        if os.path.isfile(media_path + sub_file) and not sub_file.endswith(FILE_EXTENSIONS):
            # delete all the crap that gets left in these directories except for the file itself
            count +=1
            os.remove(media_path + sub_file)
    logger.info(f"Deleted {count} file(s).")


def get_file_title(old_file_name, new_file_name):
    title_regx = r"^.+?(?:(?=\.\d{4})|(?=\(\d{2,})|(?=\(\d{2,})|(?=[Ss]\d{1,})|(?=[Ee]\d{1,})|(?=\W\d{2,}))|^.+?(?=[Ss]eason)|^.+?(?=[Ee]pisode)|^.+?\d{1,2}"
    if re.search(title_regx, old_file_name) is not None:
        file_title = re.search(title_regx, old_file_name).group()
        new_file_name += str(file_title).strip().replace(" ", ".")
        logger.info(f"Title regex matched! New file name: {new_file_name}")
        match = True
    else:
        logger.warning("Title regex could not find a match!")
        match = False
    return new_file_name, match


def get_file_season(old_file_name, new_file_name):
    season_regx = r"[Ss]eason[\s\.]\d{1,2}|[Ss]\d{1,2}|(?<=\[)\d{1,2}(?=x)|\d{1,2}(?=x\d)"
    if re.search(season_regx, old_file_name) is not None:
        file_season = re.search(season_regx, old_file_name).group()
        if "season" in file_season.lower():
            file_season = file_season.lower().replace("season", "S").replace(" ", "").replace(".", "")
        # re.sub("\d{1}", "")
        if new_file_name[-1] != ".":
            new_file_name += "."
        new_file_name += file_season.strip().replace(" ", "")
        logger.info(f"Season regex matched! New file name: {new_file_name}")
        match = True
    else:
        logger.warning("Season regex could not find a match!")
        match = False
    return new_file_name, match


def get_file_episode(old_file_name, new_file_name):
    episode_regx = r"[Ee]pisode[\s\.]\d{1,2}|[Ee]\d{1,2}|(?<=\dx)\d{1,2}"
    if re.search(episode_regx, old_file_name) is not None:
        file_episode = re.search(episode_regx, old_file_name).group()
        if "episode" in file_episode.lower():
            file_episode = file_episode.lower().replace("episode", "E").replace(" ", "").replace(".", "")
        # re.sub("\d{1}", "")
        if new_file_name[-1] != ".":
            new_file_name += "."
        new_file_name += file_episode.strip().replace(" ", "")
        logger.info(f"Episode regex matched! New file name: {new_file_name}")
        match = True
    else:
        logger.warning("Episode regex could not find a match!")
        match = False
    return new_file_name, match


def get_file_year(old_file_name, new_file_name):
    year_regx = r"(19|20)\d{2}(?!p)"
    if re.search(year_regx, old_file_name) is not None:
        file_year = re.search(year_regx, old_file_name).group()
        if new_file_name[-1] != ".":
            new_file_name += "."
        new_file_name += file_year.strip().replace(" ", ".")
        logger.info(f"File year regex matched! New file name: {new_file_name}")
        match = True
    else:
        logger.warning("Year regex could not find a match!")
        match = False
    return new_file_name, match


def get_file_resolution(old_file_name, new_file_name):
    resolution_regx = r"\d{3,4}p"
    if re.search(resolution_regx, old_file_name) is not None:
        file_resolution = re.search(resolution_regx, old_file_name).group()
        if new_file_name[-1] != ".":
            new_file_name += "."
        new_file_name += file_resolution.strip().replace(" ", ".")
        logger.info(f"Resolution regex matched! New file name: {new_file_name}")
        match = True
    else:
        logger.warning("Resolution regex could not find a match!")
        match = False
    return new_file_name, match


def rename_file_for_plex(cfg, dl_dir, file_name):
    new_file_name = ""
    # remove spaces from file name
    formatted_movie = file_name.replace(" ", ".")

    new_file_name, title_match = get_file_title(formatted_movie, new_file_name)
    new_file_name, season_match = get_file_season(formatted_movie, new_file_name)
    new_file_name, episode_match = get_file_episode(formatted_movie, new_file_name)
    new_file_name, year_match = get_file_year(formatted_movie, new_file_name)
    new_file_name, resolution_match = get_file_resolution(formatted_movie, new_file_name)

    if dl_dir is not None:
        os.rename(dl_dir + file_name, dl_dir + new_file_name)
    msg = f"Renaming finished."\
          f"\nTitle Match: {title_match}"\
          f"\nSeason Match: {season_match}"\
          f"\nFile Year Match: {year_match}"\
          f"\nEpisode Match: {episode_match}"\
          f"\nFile Resolution Match: {resolution_match}"\
          f"\nNew Name: {new_file_name}"
    logger.info(msg)
    post_msg_to_disc(msg)
    return new_file_name


def get_name_for_subs(media_path):
    for sub_file in os.listdir(media_path):
        if sub_file.endswith(FILE_EXTENSIONS):
            # grab everything but it's extension
            rename_and_move_subs(media_path)


def rename_and_move_subs(media_path):
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
                    ext = ''
                    if '3_English' in sub:
                        ext = '.en.cc.ext'
                    elif '4_English' in sub.lower():
                        ext = '.en.forced.ext'
                    elif 'English' in sub.lower():
                        ext = '.en.srt'
                    try:
                        logger.info(
                            f"Attempting to rename sub file {media_path}{sub_file}\\{sub} to:\n "
                            f"{media_path}\\{sub}{ext}"
                        )
                        os.rename(media_path + sub_file + "\\" + sub, media_path + "\\" + sub + ext)
                    except OSError as e:
                        post_msg_to_disc(f"Encountered exception processing subtitle file: {e}")
                        logger.error(f"Ran into error processing sub file: {e}")
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
                            os.rename(
                                media_path + sub_file + '\\' + sub + '\\' + sub_folder_file, media_path + sub + ext)
                            logger.info(
                                f"Attempting to rename sub file {media_path}{sub_file}\\{sub}\\{sub_folder_file} to:\n "
                                f"{media_path}{sub}{ext}"
                            )
                        except OSError as e:
                            post_msg_to_disc(f"Encountered exception processing subtitle file: {e}")
                            logger.error(f"Ran into error processing sub file: {e}")
                            continue


def _process_file(cfg, hash):
    dl_dir = cfg["disk"]["dl_path"]
    movie_dir = cfg["disk"]["movie_path"]
    tv_dir = cfg["disk"]["tv_path"]
    try:
        tor = _get_file_by_hash(hash)[0]
        name = tor["name"].encode("ascii", "ignore").decode("utf-8")
        tag = tor["tags"]

        for movie in os.listdir(dl_dir):
            logger.info(f"Inspecting file name: {movie}")
            # only rename files that have been tagged so we know where to put them
            if (movie.lower().startswith(name[:5].lower()) or name[:5].lower() in movie.lower()[:5]) and tag != "":
                try:
                    new_name = rename_file_for_plex(config, dl_dir, movie)
                    if os.path.isdir(dl_dir + movie):
                        sub_dir = dl_dir + new_name + '\\'
                        delete_extraneous_files(sub_dir)
                        get_name_for_subs(sub_dir)
                    # now move it to the new location
                    if tag == 'movie':
                        logger.info(f"File was tagged as {tag}.")
                        logger.info(f"Moving file to {movie_dir}")
                        shutil.move(dl_dir+new_name, movie_dir)
                    elif tag == 'tv':
                        logger.info(f"File was tagged as {tag}.")
                        logger.info(f"Moving file to {tv_dir}")
                        shutil.move(dl_dir+new_name, tv_dir)
                    # file completed we can safely delete it here if we didn't run into an exception
                    post_msg_to_disc(f"File finished processing without errors, deleting tor now.")
                    _delete_file(tor["hash"])
                except Exception as e:
                    logger.info(f"Encountered exception! {e}")
                    post_msg_to_disc(f"Encountered exception processing file: {e}")
                    continue
            else:
                logger.info(f"File was not tagged, skipping {movie}")
    except Exception as e:
        post_msg_to_disc(f"Encountered exception processing file: {e}")
        logger.info(f"Encountered exception! {e}")


def _get_file_by_hash(hash):
    return qb.torrents_info(torrent_hashes=hash)


def _get_list_of_all():
    # retrieve and show all torrents
    # logger.info("Getting list of all tors.")
    torrent_list = []
    for tor in qb.torrents_info():
        torrent_list.append(
            {
                "hash": tor["hash"],
                "name": tor["name"].encode("ascii", "ignore").decode("utf-8"),
                "progress": f'{tor["progress"]}',
                "state": tor["state"],
                "amount_left": tor["amount_left"],
                "tags": tor["tags"],
                "size": tor["size"],
                "eta": tor["eta"],
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


def _tag_tv(tor_hash):
    return qb.torrents_add_tags(tags='tv', torrent_hashes=tor_hash)


def _tag_movie(tor_hash):
    return qb.torrents_add_tags(tags='movie', torrent_hashes=tor_hash)


def _delete_file(tor_hash, delete_files=True):
    return qb.torrents_delete(delete_files=delete_files, torrent_hashes=tor_hash)


def _set_download_location(path):
    return qb.set_location(location=path)


def _force_start_all():
    return qb.torrents.set_force_start(enable=True, torrent_hashes='all')


def _resume_all():
    return qb.torrents.resume(torrent_hashes='all')


def _resume_one(hash):
    return qb.torrents.resume(torrent_hashes=hash)


def get_human_sizes(nbytes):
    suffixes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    i = 0
    while nbytes >= 1024 and i < len(suffixes)-1:
        nbytes /= 1024.
        i += 1
    f = ('%.2f' % nbytes).rstrip('0').rstrip('.')
    return '%s %s' % (f, suffixes[i])


def _format_tor_message(tor: dict):
    try:
        progress = round(float(tor["progress"] * 100), 2)
    except:
        progress = int(tor["progress"].split('.')[0])
    formatted_message = f'**Hash**: {tor["hash"]}\n'\
                        f'**Name**: {tor["name"].capitalize()}\n'\
                        f'**State**: {tor["state"]}\n' \
                        f'**Size**: {get_human_sizes(tor["size"])}\n' \
                        f'**Left to DL**: {get_human_sizes(tor["amount_left"])}\n'\
                        f'**ETA**: {datetime.timedelta(seconds=int(tor["eta"]))}\n'\
                        f'**Progress**: {progress}%\n'\
                        f'**Tags**: {tor["tags"]}\n'
    return formatted_message


def get_tor_list(cfg):
    tor_list = _get_list_of_all()
    formatted_message = []
    for tor in tor_list:
        formatted_message.append(
            _format_tor_message(tor)
        )
    payload = {
        "content": "\n".join(formatted_message)
    }
    # make sure we only send 2000 chars at a time which is the max for discord
    if len(payload["content"]) >= 2000:
        pieces = payload["content"].split('\n')
        segmented_message = ""
        for piece in pieces:
            # logger.info(f'length of next segment is {len(piece)}')
            if len(segmented_message) + len(piece) < 2000:
                segmented_message += piece
                # logger.info(f'length of segmented message is now: {len(segmented_message)}')
            else:
                # logger.info(f'length would have been too long!')
                payload = {"content": "\n".join(segmented_message)}
                r = requests.post(cfg["discord"]["url"], json=payload)
                logger.info("Sent message to discord!", r.status_code, r.text)
                # logger.info(f'we would have sent {len(payload["content"])}')
                segmented_message = piece
    # if it's less than the regular checks will suffice
    else:
        if payload["content"] == '':
            payload["content"] = 'There are no active Torrents!'
        r = requests.post(cfg["discord"]["url"], json=payload)
        logger.info(f"Sent message to discord! {payload['content']} with response: {r.status_code}")


def post_msg_to_disc(msg):
    config = get_config()
    payload = {"content": msg}
    r = requests.post(config["discord"]["url"], json=payload)
    logger.info(f"Sending message to discord: {msg} with response {r.status_code}")


def _send_logs(cfg):
    log_file = os.path.expandvars("%USERPROFILE%\\Desktop\\qtor.log")
    files = {
        'file': open(log_file, 'rb')
    }
    logger.info("Sending log file to discord.")
    r = requests.post(
        cfg["discord"]["url"],
        files=files,
        json={"content": "Latest Log!", "tts": False}
    )
    logger.info(f"Log post result {r.status_code}")


if __name__ == '__main__':
    config = get_config()
    files_to_be_processed = []
    # Instantiate everything we need
    # start the application
    logger.info("Starting QTOR")
    check_and_start_process(cfg=config)
    # connect to the process
    logger.info("Connecting to processes...")
    qb = connect(cfg=config)
    logger.info("Creating SQS object...")
    # create our sqs object
    sqs = boto3.resource(
        'sqs',
        region_name=config["plex"]["region"],
        aws_access_key_id=config["plex"]["aws_key_id"],
        aws_secret_access_key=config["plex"]["aws_secret_id"]
    )
    # grab the queue object
    queue = sqs.get_queue_by_name(QueueName=config["plex"]["queue_name"])

    # start the polling loop
    logger.info("Starting polling now!")
    while True:
        messages_to_delete = []
        # check for new messages
        response = retrieve_command_from_sqs(config, queue)
        # if we have a response
        for message in response:
            logger.info("New message from SQS!")
            # parse the response of message.body here
            body = json.loads(message.body)
            parse_message_body(config, body)
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
            if latest_status["hash"] not in processed_tors.keys():
                post_msg_to_disc(f'New download detected: {latest_status["name"]} // hash: {latest_status["hash"]}')
                processed_tors[latest_status["hash"]] = False
            # if the state is pausedUp
            if latest_status["state"] == "pausedUP" and latest_status["tags"] != "" and processed_tors[latest_status["hash"]] is False:
                # file is completed, start processing it
                logger.info("File has completed, automatically processing.")
                post_msg_to_disc(f'File: {latest_status["name"]} has completed! Processing it now.')
                _process_file(config, latest_status["hash"])
                # set processed to false so it doesn't alert more than once
                processed_tors[latest_status["hash"]] = True
            # elif latest_status["state"] == "pausedUP" and latest_status["tags"] == "" and processed_tors[latest_status["hash"]] is False:
            #     post_msg_to_disc(f'File: {latest_status["name"]} has completed but has not been tagged.'
            #                      f' Please tag it before it can be processed.')
