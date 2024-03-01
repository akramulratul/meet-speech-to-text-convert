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

                for participant_id, is_speaking in self.speaking_participants.items():
                    if is_speaking:
                        # Associate text with the speaking participant
                        participant_text = f"{participant_id}: {recognized_text})\n"
                        print(participant_text)  # or save to file
                print("Recognized Text:", recognized_text)
                with open("recognized_text.txt", "a") as file:
                    file.write(participant_text)
                # Save the recognized text to file
                await self.save_text_to_file(recognized_text)
            else:
                print("No recognized text found in the event.")
                participant_text = f"{participant_id}: (silent)"
                print(participant_text)  # or save to file
            pass
        await stream.aclose()

    async def save_text_to_file(self, text):
        """
        Saves the given text to a file named 'recognized_text.txt' in append mode.
        """
        with open("recognized_text.txt", "a") as file:
            file.write(f"{text}\n")





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