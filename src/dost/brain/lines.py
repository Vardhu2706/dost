"""Fixed lines per language (pre-synthesizable, never LLM-generated).

All lines are written for a male voice (masculine first-person in Hindi). Hindi and English were
written by the assistant; **every Telugu line below needs review by a native Telugu speaker**
(needs native review) before any real-world use.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lines:
    opener_a: str  # AI disclosure + greeting (always the first thing said)
    opener_q: str  # the opening question
    memory_first_call: str  # said once, on a first call that will be remembered
    welcome_back: str  # returning caller with no open loop
    secrecy: str  # "will you keep this secret?" when a summary is kept
    secrecy_no_memory: str  # same question on a call that keeps nothing
    forgot: str  # after a forget-me that deleted a record
    forgot_nothing: str  # forget-me on a call with nothing stored
    safety_q: str  # first crisis turn, spoken right after one acknowledging sentence
    telemanas: str  # by the second crisis turn; digits spoken slowly
    crisis_fallback: tuple[str, ...]  # crisis turn 1 if the LLM fails
    crisis_fallback_followup: tuple[str, ...]  # crisis turn 2+ if the LLM fails

    @property
    def opener(self) -> str:
        return f"{self.opener_a} {self.opener_q}"


HI = Lines(
    opener_a="हेलो, मैं दोस्त हूँ, एक AI आवाज़। जब मन करे, बात कर लेना।",
    opener_q="बताओ, क्या चल रहा है?",
    memory_first_call=(
        "एक बात, मैं पिछली बातें थोड़ी याद रखता हूँ ताकि अगली बार तुम्हें सब दोबारा न बताना पड़े। "
        "भुलाना हो तो बस बोल दो, 'भूल जाओ'।"
    ),
    welcome_back="फिर से बात करके अच्छा लगा।",
    secrecy=(
        "मैं एक AI आवाज़ हूँ, इसलिए राज़ रखने का वादा नहीं कर सकता। "
        "मैं पिछली बातों का बस एक छोटा सा सार याद रखता हूँ, ताकि तुम्हें सब दोबारा न बताना पड़े, "
        "और 'भूल जाओ' बोलकर तुम उसे कभी भी मिटवा सकते हो। "
        "और अगर कुछ भी सुरक्षित न लगे, तो मैं चाहूँगा कि तुम किसी असली इंसान से बात करो।"
    ),
    secrecy_no_memory=(
        "मैं एक AI आवाज़ हूँ, इसलिए राज़ रखने का वादा नहीं कर सकता। "
        "इस कॉल की बातें मैं आगे के लिए याद नहीं रखता। "
        "और अगर कुछ भी सुरक्षित न लगे, तो मैं चाहूँगा कि तुम किसी असली इंसान से बात करो।"
    ),
    forgot="ठीक है। मैंने पिछली सारी बातें मिटा दी हैं।",
    forgot_nothing="ठीक है। इस कॉल की बातें मैं वैसे भी आगे याद नहीं रखता।",
    safety_q="क्या तुम अभी सुरक्षित हो? और क्या तुम खुद को नुकसान पहुँचाने के बारे में सोच रहे हो?",
    telemanas=(
        "तुम Tele-MANAS पर बात कर सकते हो। यह मुफ़्त है और चौबीसों घंटे चालू रहता है। "
        "नंबर है: एक, चार, चार, एक, छह।"
    ),
    crisis_fallback=(
        "मैं यहीं हूँ, तुम्हारे साथ।",
        "क्या तुम अभी सुरक्षित हो? क्या तुम खुद को नुकसान पहुँचाने की सोच रहे हो?",
    ),
    crisis_fallback_followup=(
        "मैं यहीं हूँ, तुम्हारे साथ।",
        "क्या मैं नंबर दोबारा बताऊँ, या बताओ अभी क्या मदद करेगा?",
    ),
)

EN = Lines(
    opener_a="Hello, I'm Dost, an AI voice, not a person. Talk to me whenever you feel like it.",
    opener_q="So, what's going on?",
    memory_first_call=(
        "One thing: I remember a short summary of past calls, so you don't have to tell me "
        "everything again. If you want it gone, just say 'forget it'."
    ),
    welcome_back="Good to hear from you again.",
    secrecy=(
        "I'm an AI voice, so I can't promise to keep secrets. I keep a short summary of past calls "
        "so you don't have to repeat yourself, and you can say 'forget it' any time to delete it. "
        "If something feels unsafe, I'd want you to talk to a real person."
    ),
    secrecy_no_memory=(
        "I'm an AI voice, so I can't promise to keep secrets. I don't keep anything from this call "
        "for later. If something feels unsafe, I'd want you to talk to a real person."
    ),
    forgot="Okay. I've deleted everything I kept from past calls.",
    forgot_nothing="Okay. I don't keep anything from this call anyway.",
    safety_q="Are you safe right now? And are you thinking of hurting yourself?",
    telemanas=(
        "You can talk to Tele-MANAS. It's free and open all day and night. "
        "The number is: one, four, four, one, six."
    ),
    crisis_fallback=(
        "I'm right here with you.",
        "Are you safe right now? Are you thinking of hurting yourself?",
    ),
    crisis_fallback_followup=(
        "I'm right here with you.",
        "Would you like me to say the number again, or tell me what would help right now?",
    ),
)

# TELUGU: needs native review (every string). Voice: tarun_te_narration (needs an audition).
TE = Lines(
    opener_a="హలో, నేను దోస్త్ ని, ఒక AI వాయిస్ ని, మనిషిని కాదు.",
    opener_q="ఏం జరుగుతోంది, చెప్పు?",
    memory_first_call=(
        "ఒక విషయం, గత కాల్స్ లోని విషయాల చిన్న సారాంశాన్ని నేను గుర్తుంచుకుంటాను, "
        "మళ్ళీ అన్నీ చెప్పాల్సిన అవసరం లేకుండా. అది తొలగించాలంటే 'మర్చిపో' అని చెప్పు."
    ),
    welcome_back="మళ్ళీ మాట్లాడటం సంతోషంగా ఉంది.",
    secrecy=(
        "నేను AI వాయిస్ ని, కాబట్టి రహస్యం ఉంచుతానని మాట ఇవ్వలేను. "
        "గత కాల్స్ లోని విషయాల చిన్న సారాంశాన్ని మాత్రమే గుర్తుంచుకుంటాను, మళ్ళీ చెప్పాల్సిన అవసరం లేకుండా. "
        "'మర్చిపో' అని చెప్తే ఎప్పుడైనా అది తొలగిస్తాను. "
        "ఏదైనా ప్రమాదంగా అనిపిస్తే, నిజమైన మనిషితో మాట్లాడమని కోరుకుంటాను."
    ),
    secrecy_no_memory=(
        "నేను AI వాయిస్ ని, కాబట్టి రహస్యం ఉంచుతానని మాట ఇవ్వలేను. "
        "ఈ కాల్ లోని విషయాలను నేను తర్వాత కోసం గుర్తుంచుకోను. "
        "ఏదైనా ప్రమాదంగా అనిపిస్తే, నిజమైన మనిషితో మాట్లాడమని కోరుకుంటాను."
    ),
    forgot="సరే. గత కాల్స్ నుంచి నేను గుర్తుంచుకున్నవన్నీ తొలగించాను.",
    forgot_nothing="సరే. ఈ కాల్ లోని విషయాలు నేను ఎలాగూ గుర్తుంచుకోను.",
    safety_q="ఇప్పుడు నువ్వు సురక్షితంగా ఉన్నావా? నిన్ను నువ్వు హాని చేసుకోవాలని అనిపిస్తోందా?",
    telemanas=(
        "మీరు Tele-MANAS తో మాట్లాడవచ్చు. ఇది ఉచితం, ఎప్పుడైనా చేయవచ్చు. "
        "నంబర్: ఒకటి, నాలుగు, నాలుగు, ఒకటి, ఆరు."
    ),
    crisis_fallback=(
        "నేను ఇక్కడే ఉన్నాను, నీతో.",
        "ఇప్పుడు నువ్వు సురక్షితంగా ఉన్నావా? నిన్ను నువ్వు హాని చేసుకోవాలని అనిపిస్తోందా?",
    ),
    crisis_fallback_followup=(
        "నేను ఇక్కడే ఉన్నాను, నీతో.",
        "నంబర్ మళ్ళీ చెప్పనా, లేదా ఇప్పుడు ఏమి సహాయపడుతుందో చెప్పు?",
    ),
)

LINES: dict[str, Lines] = {"hi": HI, "en": EN, "te": TE}
TTS_LANG = {"hi": "hi-IN", "en": "en-IN", "te": "te-IN"}


def lines_for(lang: str) -> Lines:
    return LINES.get(lang, HI)
