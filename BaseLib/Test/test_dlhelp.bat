set PYTHONPATH=..\..

python test_dlhelp.py singtest_good_2fast
python test_dlhelp.py singtest_bad_2fast_dlhelp
python test_dlhelp.py singtest_bad_2fast_metadata_not_bdecodable
python test_dlhelp.py singtest_bad_2fast_metadata_not_dict1
python test_dlhelp.py singtest_bad_2fast_metadata_not_dict2
python test_dlhelp.py singtest_bad_2fast_metadata_empty_dict
python test_dlhelp.py singtest_bad_2fast_metadata_wrong_dict_keys
python test_dlhelp.py singtest_bad_2fast_metadata_bad_torrent1
python test_dlhelp.py singtest_bad_2fast_metadata_bad_torrent2
python test_dlhelp.py singtest_bad_2fast_metadata_bad_torrent3