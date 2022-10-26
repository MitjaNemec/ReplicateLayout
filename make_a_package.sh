#! /bin/bash

# refresh derived resources
inkscape replicate_layout_dark.svg -w 24 -h 24 -o replicate_layout_dark.png
inkscape replicate_layout_light.svg -w 24 -h 24 -o replicate_layout_light.png
inkscape replicate_layout_light.svg -w 64 -h 64 -o replicate_layout.png

# refresh the GUI design
~/WxFormBuilder/bin/wxformbuilder -g replicate_layout_GUI.fbp
~/WxFormBuilder/bin/wxformbuilder -g error_dialog_GUI.fpb

# grab version and parse it into metadata.json
cp metadata_source.json metadata_package.json
version=`cat version.txt`
# remove all but the latest version in package metadata
python parse_metadata_json.py
sed -i -e "s/VERSION/$version/g" metadata.json

# cut the download, sha and size fields
sed -i '/download_url/d' metadata.json
sed -i '/download_size/d' metadata.json
sed -i '/install_size/d' metadata.json
sed -i '/download_sha256/d' metadata.json

# prepare the package
mkdir plugins
cp replicate_layout_dark.png plugins
cp replicate_layout_light.png plugins
cp __init__.py plugins
cp action_replicate_layout.py plugins
cp replicate_layout.py plugins
cp remove_duplicates.py plugins
cp replicate_layout_GUI.py plugins
cp error_dialog_GUI.py plugins
cp version.txt plugins
mkdir resources
cp replicate_layout.png resources/icon.png

zip -r ReplicateLayout-$version-pcm.zip plugins resources metadata.json

# clean up
rm -r resources
rm -r plugins
rm metadata.json

# get the sha, size and fill them in the metadata
cp metadata_source.json metadata.json
version=`cat version.txt`
sed -i -e "s/VERSION/$version/g" metadata.json
zipsha=`sha256sum ReplicateLayout-$version-pcm.zip | xargs | cut -d' ' -f1`
sed -i -e "s/SHA256/$zipsha/g" metadata.json
unzipsize=`unzip -l ReplicateLayout-$version-pcm.zip | tail -1 | xargs | cut -d' ' -f1`
sed -i -e "s/INSTALL_SIZE/$unzipsize/g" metadata.json
dlsize=`ls -al ReplicateLayout-$version-pcm.zip | tail -1 | xargs | cut -d' ' -f5`
sed -i -e "s/DOWNLOAD_SIZE/$dlsize/g" metadata.json
