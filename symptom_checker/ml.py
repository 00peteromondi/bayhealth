def predict_disease(symptom_text: str):
    symptoms = symptom_text.lower()
    if "chest pain" in symptoms or "shortness of breath" in symptoms:
        return {
            "disease": "Possible cardiac or respiratory emergency",
            "confidence": 0.78,
            "risk_level": "high",
            "guidance": "Seek immediate clinical evaluation or emergency assistance.",
        }
    if "fever" in symptoms and "cough" in symptoms:
        return {
            "disease": "Flu-like illness",
            "confidence": 0.85,
            "risk_level": "moderate",
            "guidance": "Book a consultation, hydrate, and monitor worsening symptoms.",
        }
    if "headache" in symptoms and "fatigue" in symptoms:
        return {
            "disease": "Viral syndrome or stress-related presentation",
            "confidence": 0.64,
            "risk_level": "low",
            "guidance": "Rest, hydration, and outpatient review if persistent.",
        }
    return {
        "disease": "Non-specific symptoms",
        "confidence": 0.52,
        "risk_level": "low",
        "guidance": "Arrange a professional consultation for a complete assessment.",
    }
