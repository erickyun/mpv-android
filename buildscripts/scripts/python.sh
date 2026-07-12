#!/bin/bash -e

. ../../include/path.sh
. ../../include/depinfo.sh

if [ "$1" == "build" ]; then
	true
elif [ "$1" == "clean" ]; then
	rm -rf _build$ndk_suffix
	exit 0
else
	exit 255
fi

abi=armeabi-v7a
[[ "$ndk_triple" == "aarch64"* ]] && abi=arm64-v8a
[[ "$ndk_triple" == "x86_64"* ]] && abi=x86_64
[[ "$ndk_triple" == "i686"* ]] && abi=x86

hostpy=python${v_python:0:4}
if ! command -v $hostpy; then
	echo "compatible Python ($hostpy) is required to build"
	exit 1
fi

recompile_py () {
	find . -name '*.pyc' -delete
	$hostpy -OO -m compileall -b -j4 .
	find . -name "__pycache__" -print0 | xargs -0 -- rm -rf
}

prune_stdlib () {
	local delete=(
		pydoc_data turtledemo
		tkinter sqlite3 venv ensurepip dbm
		idlelib multiprocessing unittest
	)
	rm -r "${delete[@]}"
}

export READELF=llvm-readelf
export CFLAGS="-Os -I$prefix_dir/include"
export LDFLAGS="-L$prefix_dir/lib"

mkdir -p _build$ndk_suffix
cd _build$ndk_suffix

ac_cv_file__dev_ptmx=no ac_cv_file__dev_ptc=no \
MODULE_BUILDTYPE=static \
../configure --host=$ndk_triple --build=${ndk_triple%%-*} \
	--enable-ipv6 --disable-shared --without-ensurepip \
	--disable-test-modules --with-build-python
make -j$cores

rm -rf dest
make DESTDIR="$PWD/dest" install
inst=$PWD/dest/usr/local

out=$(realpath ../../../../app/src/main/assets/py.$abi)
mkdir -p $out
rm -f $out/python*

cp -v python $out/python3
llvm-strip -s $out/python3

pushd $inst/lib/python3.*
prune_stdlib
recompile_py
zip -9 $out/python3${v_python:2:2}.zip -R '*.pyc'
popd
