#!/usr/bin/env python3
"""
Wave splicing program for mixtapes
Copyright 2026 Damian Yerrick

Overall file structure for splicethem.json:
{"src":[source recording, ...],"cue":["m:s",...]}
Each source recording:
{"filename":"something.wav",
 "cuts":["m:s.sss-m:s.sss",...]
 "fadein":"m:s-m:s",
 "fadeout":"m:s-m:s",
 "overlap":"m:s"
}
filename: path to a 16-bit linear PCM wave
cuts: optional list of time ranges to remove
fadeintime: optional time range to fade in
fadeouttime: optional time range to fade out
overlappt: optional time at which to start next track
cue: times in the final at which to make new wav files
"""
from __future__ import with_statement, division, print_function
import wave, json, array, itertools, time
try:
    xrange
except NameError:
    xrange = range
little = array.array('H', [0x0001]).tostring()[0]
if isinstance(little, str): little = ord(little)

sample_rate = 44100
sector_length = 44100//75
n_channels = 2

def parse_time(timespec):
    hms = timespec.split(':', 2)
    s = 0
    for part in hms[:-1]:
        s = (s + int(part)) * 60
    return s * sample_rate + int(round(float(hms[-1]) * sample_rate))

def makecuts(data, cues, n_channels):
    cues = [line.split('-', 1) for line in cues]
    cues = sorted(((parse_time(start), parse_time(end))
                   for (start, end) in cues),
                  reverse=True)
    samples_cut = 0
    for start, end in cues:
        samples_cut += end - start
        del data[start * n_channels:end * n_channels]
    return samples_cut

def writeseg(cuecount, data):
##    print("writeseg skipped")
##    return
    wavdst = wave.open("out%02d.wav" % cuecount, "wb")
    wavdst.setnchannels(n_channels)
    wavdst.setsampwidth(2)
    wavdst.setframerate(sample_rate)
    wavdst.setnframes(len(data) // (2 * n_channels))
    wavdst.writeframes(data)
    wavdst.close()

def writesegs(datatowrite):
    global cuecount, prevcue
    while (cuecount < len(cues)
           and (cues[cuecount] - prevcue) * n_channels <= len(datatowrite)):
        file_nframes = cues[cuecount] - prevcue
        print("writing %d frame file" % file_nframes)
        thisfiledata = datatowrite[:file_nframes * n_channels]
        del datatowrite[:file_nframes * n_channels]
        prevcue = cues[cuecount]
        cuecount += 1
        if not little: thisfiledata.byteswap()
        writeseg(cuecount, thisfiledata.tostring())

with open("splicethem.json") as infp:
    cmds = json.load(infp)
overlapdata = array.array('h')
datatowrite = array.array('h')
cues = [parse_time(row) // sector_length * sector_length
        for row in cmds.get('cue', [])]
cuecount = prevcue = 0
for srcspec in cmds['src']:
    if srcspec.get('disabled'):
        continue
    wavsrc = wave.open(srcspec['filename'], 'rb')
    if wavsrc.getsampwidth() != 2:
        raise ValueError("%s: unsupported sample width %d"
                         % (srcspec['filename'], wavsrc.getsampwidth()))
    if wavsrc.getcomptype() != 'NONE':
        raise ValueError("%s: unsupported sample compression %s (%s)"
                         % (srcspec['filename'], wavsrc.getcomptype(), wavsrc.getcompname()))
    src_nchannels = wavsrc.getnchannels()
    if src_nchannels not in (1, 2):
        raise ValueError("%s: unsupported number of channels %d"
                         % (srcspec['filename'], src_nchannels))
    src_nframes = wavsrc.getnframes()
    fadeintime = srcspec.get('fadein')
    if fadeintime:
        fadeintime = [parse_time(t) for t in fadeintime.split('-', 1)]
    else:
        fadeintime = [0, 0]
    if len(fadeintime) < 2:
        fadeintime[:0] = [0]
    fadeouttime = srcspec.get('fadeout')
    if fadeouttime:
        fadeouttime = [parse_time(t) for t in fadeouttime.split('-', 1)]
    else:
        fadeouttime = [src_nframes, src_nframes]
    if len(fadeouttime) < 2:
        fadeouttime.append(src_nframes)
    overlappt = srcspec.get('overlap')
    overlappt = parse_time(overlappt) if overlappt else fadeouttime[1]

    # Crop off the data before the fade-in.
    # Wave_read.tell() is in bytes but setpos() is in frames
    # for some reason
    wavsrc.setpos(fadeintime[0])
    src_nframes -= fadeintime[0]
    fadeouttime[0] -= fadeintime[0]
    fadeouttime[1] -= fadeintime[0]
    overlappt -= fadeintime[0]
    fadeintime = fadeintime[1] - fadeintime[0]

    # Read up through the fade-out
    src_nframes = min(src_nframes, fadeouttime[1])
    srcdata = array.array('h', wavsrc.readframes(src_nframes))
    wavsrc.close()
    wavsrc = None
    if not little:
        srcdata.byteswap()

    print("%s: %d samples, %.2f seconds, %d channels"
          % (srcspec['filename'], src_nframes, src_nframes / sample_rate, src_nchannels))

    # apply fade in
    tstart = time.time()
    fodenom = 1/fadeintime if fadeintime else 1
    fofac = [(t + .5) * fodenom for t in xrange(fadeintime)]
    fofac = [f for f in fofac for i in xrange(src_nchannels)]
    fosrc = srcdata[:fadeintime * src_nchannels]
    fosrc = array.array('h', (int(round(s * f)) for s, f in zip(fosrc, fofac)))
    srcdata[:fadeintime * src_nchannels] = fosrc
    tfade = time.time() - tstart
    if tfade > 2:
        print("fade in took %.1f s to calculate" % tfade)

    tstart = time.time()
    fodenom = (fadeouttime[1] - fadeouttime[0])
    fodenom = 1/(fodenom*fodenom) if fodenom else 1
    fofac = [t - fadeouttime[1] + .5
             for t in xrange(fadeouttime[0], src_nframes)]
    fofac = [f * f * fodenom for f in fofac]
    fofac = [f for f in fofac for i in xrange(src_nchannels)]
    fosrc = srcdata[fadeouttime[0] * src_nchannels:]
    fosrc = array.array('h', (int(round(s * f)) for s, f in zip(fosrc, fofac)))
    srcdata[fadeouttime[0] * src_nchannels:] = fosrc
    tfade = time.time() - tstart
    if tfade > 2:
        print("fade out took %.1f s to calculate" % tfade)

    # apply cuts
    overlappt -= makecuts(srcdata, srcspec.get('cuts', []), n_channels)

    # convert to stereo
    if n_channels == 2 and src_nchannels == 1:
        print("converting mono to stereo")
        stereodata = array.array('h', (c for c in srcdata for i in (0, 1)))
    elif n_channels == src_nchannels:
        stereodata = srcdata
    else:
        raise ValueError("unsupported channel count")
    srcdata = None

    # Pad with silence to overlap point if needed
    if overlappt > src_nframes:
        stereodata.extend(array.array('h', [0]) * ((overlappt - src_nframes) * n_channels))
    if len(overlapdata) > len(stereodata):
        stereodata.extend(array.array('h', [0]) * (len(overlapdata) - len(stereodata)))

    # Add overlapdata to start of stereodata
    tstart = time.time()
    for i, ovsample in enumerate(overlapdata):
        stereodata[i] = min(32767, max(-32767, ovsample + stereodata[i]))
    tfade = time.time() - tstart
    if tfade > 2:
        print("overlap took %.1f s to calculate" % tfade)

    print("  fadein: %.2f; fadeout: %.2f-%.2f; start next at %.2f\n"
          "  overlap data: %.2f"
          % (fadeintime / sample_rate,
             fadeouttime[0] / sample_rate, fadeouttime[1] / sample_rate,
             overlappt / sample_rate,
             len(overlapdata) / (sample_rate * n_channels)))
    datatowrite.extend(stereodata[:overlappt * n_channels])
    overlapdata = stereodata[overlappt * n_channels:]
    stereodata = None
    writesegs(datatowrite)

datatowrite.extend(overlapdata)
overlapdata = None
cuecount += 1
if not little: datatowrite.byteswap()
writeseg(cuecount, datatowrite.tostring())
datatowrite = None

# bag: "I'll Drown"
