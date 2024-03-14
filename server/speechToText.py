import asyncio
from datetime import datetime
import json
import logging
from typing import Optional

from livekit import agents, rtc
from livekit.plugins import deepgram, silero


class PainterAgent:
    @classmethod
    async def create(cls, ctx: agents.JobContext):
        agent = PainterAgent(ctx)
        await agent.start()

    def __init__(self, ctx: agents.JobContext):
        # plugins
        self.vad = silero.VAD()
        self.speaking_participants = {}
        self.ctx = ctx
        self.chat = rtc.ChatManager(ctx.room)
        self.prompt: Optional[str] = None
        self.current_image: Optional[rtc.VideoFrame] = None
        # setup callbacks
        def subscribe_cb(
            track: rtc.Track,
            publication: rtc.TrackPublication,
            participant: rtc.RemoteParticipant,
        ):
            self.ctx.create_task(self.audio_track_worker(track))
            
            if isinstance(track, rtc.RemoteAudioTrack):
                self.speaking_participants[participant.sid] = True
                
                print(f"participant{str(self)}")
                print(f"Participant with ID '{participant.sid}' subscribed to audio track '{track.sid}'")
            else:
        # Handle other track types differently (optional)
                print(f"Received unexpected track type: {type(track)}")
        def process_chat(msg: rtc.ChatMessage):
            self.prompt = msg.message

        self.ctx.room.on("track_subscribed", subscribe_cb)
        self.chat.on("message_received", process_chat)

    async def start(self):
        # give a bit of time for the user to fully connect so they don't miss
        # the welcome message
        await asyncio.sleep(1)
        # create_task is used to run coroutines in the background
        self.ctx.create_task(
            self.chat.send_message(
                "I am testing deepgram STT"
            )
        )

        self.update_agent_state("listening")

    def update_agent_state(self, state: str):
        metadata = json.dumps(
            {
                "agent_state": state,
            }
        )
        self.ctx.create_task(self.ctx.room.local_participant.update_metadata(metadata))

    async def audio_track_worker(self, track: rtc.Track):
        stt = deepgram.STT()
        stt_stream = stt.stream()
        audio_stream = rtc.AudioStream(track)

        self.ctx.create_task(self.process_text_from_speech(stt_stream))
        async for audio_frame_event in audio_stream:
            stt_stream.push_frame(audio_frame_event.frame)
        await stt_stream.flush()

    async def process_text_from_speech(self, stream):
        async for event in stream:
            if not event.is_final:
                # received a partial result, STT result be updated as confidence increases
                continue
            if event.alternatives:
                first_alternative = event.alternatives[0]
                recognized_text = first_alternative.text  # Adjust this attribute access as necessary
                speaking_participant = None
                # speaking_participant_identity = None
                for participant_id, is_speaking in self.speaking_participants.items():
                    if is_speaking:
                        speaking_participant = participant_id
                        # speaking_participant_identity = self.ctx.room.participants[participant_id].identity
                        break

                if speaking_participant and len(recognized_text):
                    await self.chat.send_message(recognized_text)
                else:
                    print("No speaker identified for recognized text.")
                    message = f"(Unknown): {recognized_text}"  # Handle unidentified speaker
            else:
                print("No recognized text found in the event.")
                pass
        await stream.aclose()



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    async def job_request_cb(job_request: agents.JobRequest):
        await job_request.accept(
            PainterAgent.create,
            identity="painter",
            name="Painter",
            # subscribe to all audio tracks automatically
            auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY,
            # disconnect when the last participant leaves
            auto_disconnect=agents.AutoDisconnect.DEFAULT,
        )

    worker = agents.Worker(request_handler=job_request_cb)
    agents.run_app(worker)