"""Actual output/receiver scheduling, synthetic payloads and controlled clocks."""
from pathlib import Path
import socket
import sys
import threading

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_phone_webcam import NativeWebcamSession,WebcamUnavailable,VIDEO_BYTES,AUDIO_BYTES
from magnolie_phone_camera_receiver import WebcamReceiveRun
from magnolie_phone_camera_transport import WebcamMediaSocket


class Clock:
    def __init__(self):self.now=5.;self.waits=[];self.hook=None
    def __call__(self):return self.now
    def wait(self,delay):
        assert 0 < delay <= .010
        self.waits.append(delay);self.now+=delay
        if self.hook:return self.hook()
        return False


class Output:
    def __init__(self,clock):self.clock=clock;self.frames=[];self.closed=False
    def write(self,data):
        assert not self.closed;self.frames.append((self.clock(),data));return True
    def close(self):self.closed=True


def session(clock,guard=lambda:None,**options):
    return NativeWebcamSession('/controlled/virtual-output',guard,clock=clock,wait=clock.wait,
        video_factory=lambda _:Output(clock),audio_factory=lambda _:Output(clock),**options)


def finish(value):
    value.close();value.monitor.join(1);assert not value.monitor.is_alive()


def frame(value,stream,sequence,pts):
    return value.write(stream,sequence,pts,bytes(VIDEO_BYTES if stream=='video' else AUDIO_BYTES))


def test_burst_packets_use_one_original_presentation_anchor_for_both_tracks():
    clock=Clock();value=session(clock)
    try:
        frame(value,'video',0,0);frame(value,'audio',0,0)
        frame(value,'audio',1,20000);frame(value,'audio',2,40000)
        frame(value,'video',1,66667)
        assert [stamp for stamp,_ in value.audio.frames]==pytest.approx([5.,5.02,5.04])
        assert [stamp for stamp,_ in value.video.frames]==pytest.approx([5.,5.066667])
        assert max(clock.waits)<=.010
    finally:finish(value)


def test_large_valid_pts_preserve_exact_relative_spacing_without_new_anchor():
    clock=Clock();value=session(clock,muted=True);pts=9_007_199_254_600_000
    try:
        frame(value,'video',0,pts);frame(value,'video',1,pts+66667)
        assert value.video.frames[-1][0]==pytest.approx(5.066667)
    finally:finish(value)


@pytest.mark.parametrize('mode',['ahead','late','clock_backwards','clock_nan','frozen_wait'])
def test_invalid_or_stalled_presentation_time_retires_outputs_without_reanchoring(mode):
    clock=Clock();value=session(clock,muted=True)
    try:
        frame(value,'video',0,0)
        pts=66667
        if mode=='ahead':pts=250001
        elif mode=='late':clock.now+=.400
        elif mode=='clock_backwards':clock.now-=.001
        elif mode=='clock_nan':clock.now=float('nan')
        else:value.wait=lambda delay:False
        with pytest.raises(WebcamUnavailable,match='presentation_'):frame(value,'video',1,pts)
        assert value.closed and value.video.closed and len(value.video.frames)==1
        with pytest.raises(WebcamUnavailable):frame(value,'video',1,pts)
    finally:finish(value)


def test_mild_lateness_does_not_reset_anchor_or_add_another_delay():
    clock=Clock();value=session(clock,muted=True)
    try:
        frame(value,'video',0,0);clock.now+=.100
        frame(value,'video',1,66667)
        assert value.video.frames[-1][0]==5.1 and not clock.waits
        frame(value,'video',2,133334)
        assert value.video.frames[-1][0]==pytest.approx(5.133334)
    finally:finish(value)


def test_guard_withdrawal_during_presentation_wait_writes_neither_stale_track():
    clock=Clock();current=[True]
    def guard():
        if not current[0]:raise PermissionError('original capture context revoked')
    value=session(clock,guard)
    try:
        frame(value,'video',0,0);frame(value,'audio',0,0)
        clock.hook=lambda:current.__setitem__(0,False)
        with pytest.raises(PermissionError):frame(value,'audio',1,20000)
        assert value.video.closed and value.audio.closed
        assert len(value.audio.frames)==len(value.video.frames)==1
    finally:finish(value)


def test_explicit_close_can_retire_outputs_while_writer_is_waiting_without_state_lock():
    clock=Clock();value=session(clock,muted=True);entered=threading.Event();errors=[]
    def wait(delay):entered.set();return value.stop.wait(2)
    value.wait=wait
    def write():
        try:frame(value,'video',1,66667)
        except Exception as error:errors.append(error)
    try:
        frame(value,'video',0,0)
        worker=threading.Thread(target=write);worker.start()
        assert entered.wait(1)
        closer=threading.Thread(target=value.close);closer.start();closer.join(.5)
        assert not closer.is_alive(),'Presentation wait held the state lock and blocked stop'
        worker.join(1);assert not worker.is_alive() and errors
        assert value.video.closed and len(value.video.frames)==1
    finally:finish(value)


def test_actual_encrypted_receiver_uses_the_same_clock_before_native_output_writes():
    clock=Clock();left,right=socket.socketpair();outputs=[]
    def factory(device,guard,**options):
        value=session(clock,guard,**options);outputs.append(value);return value
    secret=b's'*32;identity='a'*32
    run=WebcamReceiveRun(left,identity,secret,'/controlled/virtual-output',lambda:None,output_factory=factory)
    sender=WebcamMediaSocket(right,identity,secret,lambda:None,sending=True)
    try:
        for stream,seq,pts in [('video',0,0),('audio',0,0),('audio',1,20000),('video',1,66667)]:
            sender.send(stream,seq,pts,bytes(VIDEO_BYTES if stream=='video' else AUDIO_BYTES))
        # Bounded wait for the ACTUAL original receive worker, not queued flags.
        import time
        deadline=time.monotonic()+2
        while len(outputs[0].video.frames)<2 and time.monotonic()<deadline:time.sleep(.005)
        assert outputs[0].video.frames[-1][0]==pytest.approx(5.066667)
        assert outputs[0].audio.frames[-1][0]==pytest.approx(5.02)
        assert run.state=='streaming' and run.error is None
    finally:
        run.stop();sender.close()
