import pytest
from qtor import get_file_resolution, get_file_episode, get_file_title, get_file_year, get_file_season


@pytest.mark.parametrize(
    "original_file_name, formatted_name",
    [
        (
                "Planet.Earth.III.S01.2160p.iP.WEB-DL.AAC2.0.HEVC-NTb",
                "Planet.Earth.III.S01.2160p",
        ),
        (
                "Twin Peaks Season 1 Complete DVDRip - x264 - MKV by RiddlerA",
                "Twin.Peaks.S1",
        ),
    ]
)
def test_movie_naming(original_file_name, formatted_name):
    new_file_name = ''
    new_file_name, title_match = get_file_title(original_file_name, new_file_name)
    new_file_name, season_match = get_file_season(original_file_name, new_file_name)
    new_file_name, episode_match = get_file_episode(original_file_name, new_file_name)
    new_file_name, year_match = get_file_year(original_file_name, new_file_name)
    new_file_name, resolution_match = get_file_resolution(original_file_name, new_file_name)
    assert formatted_name == new_file_name
