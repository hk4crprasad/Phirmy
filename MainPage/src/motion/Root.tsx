import { Composition } from "remotion";
import { ConversationFilm } from "./ConversationFilm";
import "./fonts.css";
import narration from "./narration-manifest.json";
export const RemotionRoot = () => (
  <>
    <Composition
      id="VoiceConversations"
      component={ConversationFilm}
      width={1000}
      height={640}
      fps={30}
      durationInFrames={narration.voice.duration}
      defaultProps={{ scenario: "voice" }}
    />
    <Composition
      id="CustomerSupport"
      component={ConversationFilm}
      width={1000}
      height={640}
      fps={30}
      durationInFrames={narration.support.duration}
      defaultProps={{ scenario: "support" }}
    />
    <Composition
      id="LeadQualification"
      component={ConversationFilm}
      width={1000}
      height={640}
      fps={30}
      durationInFrames={narration.leads.duration}
      defaultProps={{ scenario: "leads" }}
    />
    <Composition
      id="AppointmentBooking"
      component={ConversationFilm}
      width={1000}
      height={640}
      fps={30}
      durationInFrames={narration.booking.duration}
      defaultProps={{ scenario: "booking" }}
    />
  </>
);
