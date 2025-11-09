import re
import io
import zipfile
from lxml import etree
import streamlit as st

# --------- FORMAT PARSER (same logic as your Tkinter version) --------- #
def parse_guided_format(text, q_sep, opt_regex, answer_prefix, explanation_prefix):
    try:
        question_blocks = re.split(q_sep, text.strip())
        questions = []
        for idx, block in enumerate(question_blocks, start=1):
            block = block.strip()
            if not block:
                continue

            lines = block.split('\n')
            if not lines:
                continue

            # Clean question line
            question_text = re.sub(r'^\*\*(.*?)\*\*$', r'\1', lines[0].strip())
            question_text = re.sub(r'^Question \d+:', '', question_text).strip().strip("*").strip()

            options, answer, explanation = [], None, None

            for line in lines[1:]:
                line = line.strip()
                if not line:
                    continue

                is_starred = line.startswith("*")
                clean_line = re.sub(r'^\*+', '', line).strip()

                # Option lines (A), B), etc.)
                if re.match(opt_regex, clean_line):
                    options.append(clean_line)
                    if is_starred:
                        answer = re.sub(r'^[A-Da-d1-9]+\)\s*', '', clean_line).strip()
                # Answer line
                elif line.lower().startswith(answer_prefix.lower()):
                    answer_line = line[len(answer_prefix):].strip()
                    answer = re.sub(r'^[A-Da-d1-9]+\)\s*', '', answer_line).strip()
                # Explanation line
                elif line.lower().startswith(explanation_prefix.lower()):
                    explanation = line[len(explanation_prefix):].strip()
                # Starred but unlabeled correct option
                elif is_starred:
                    options.append(clean_line)
                    answer = clean_line

            if len(options) < 2:
                raise ValueError(f"Not enough options in question #{idx}: \"{question_text}\"")
            if not answer:
                raise ValueError(f"Missing answer in question #{idx}: \"{question_text}\"")
            if not explanation:
                raise ValueError(f"Missing explanation in question #{idx}: \"{question_text}\"")

            questions.append({
                'question': question_text,
                'options': options,
                'answer': answer,
                'explanation': explanation
            })

        if not questions:
            raise ValueError("No valid questions found. Check your format settings.")

        return questions

    except Exception as e:
        raise ValueError(f"Guided format parsing failed: {e}")

# --------- QTI CREATOR (returns XML bytes instead of writing to disk) --------- #
def create_qti_bytes(questions, points_per_question: float) -> bytes:
    qti = etree.Element("questestinterop")
    for i, q in enumerate(questions):
        item = etree.SubElement(qti, "item", ident=f"q{i+1}", title=f"Question {i+1}")

        presentation = etree.SubElement(item, "presentation")
        flow = etree.SubElement(presentation, "flow")
        material = etree.SubElement(flow, "material")
        mattext = etree.SubElement(material, "mattext")
        mattext.text = q['question']

        response_lid = etree.SubElement(flow, "response_lid", ident="response1", rcardinality="Single")
        render_choice = etree.SubElement(response_lid, "render_choice")

        for option_id, option in enumerate(q['options'], start=1):
            response_label = etree.SubElement(render_choice, "response_label", ident=f"option{option_id}")
            mat = etree.SubElement(response_label, "material")
            mattext = etree.SubElement(mat, "mattext")
            clean_option = re.sub(r'^[A-Da-d1-9]+\)\s*', '', option).strip()
            mattext.text = clean_option

        resprocessing = etree.SubElement(item, "resprocessing")
        outcomes = etree.SubElement(resprocessing, "outcomes")
        etree.SubElement(outcomes, "decvar", varname="SCORE", vartype="Decimal", default=str(points_per_question))

        # Correct response
        correct_resp = etree.SubElement(resprocessing, "respcondition", title="correct")
        conditionvar = etree.SubElement(correct_resp, "conditionvar")
        varequal = etree.SubElement(conditionvar, "varequal", respident="response1")

        try:
            correct_option_id = next(
                (idx for idx, opt in enumerate(q['options'], 1)
                 if q['answer'].strip().lower() ==
                    re.sub(r'^[A-Da-d1-9]+\)\s*', '', opt).strip().lower()),
                1
            )
            varequal.text = f"option{correct_option_id}"
        except Exception:
            varequal.text = "option1"

        etree.SubElement(correct_resp, "setvar", action="Set").text = str(points_per_question)

        # Incorrect response
        incorrect_resp = etree.SubElement(resprocessing, "respcondition", title="incorrect")
        etree.SubElement(incorrect_resp, "conditionvar")
        etree.SubElement(incorrect_resp, "setvar", action="Set").text = "0"

        # Feedback
        itemfeedback_correct = etree.SubElement(item, "itemfeedback", ident="feedback_correct")
        material_correct = etree.SubElement(itemfeedback_correct, "material")
        mattext_correct = etree.SubElement(material_correct, "mattext")
        mattext_correct.text  = q['explanation']
        etree.SubElement(correct_resp, "displayfeedback", feedbacktype="Response", linkrefid="feedback_correct")

        itemfeedback_incorrect = etree.SubElement(item, "itemfeedback", ident="feedback_incorrect")
        material_incorrect = etree.SubElement(itemfeedback_incorrect, "material")
        mattext_incorrect = etree.SubElement(material_incorrect, "mattext")
        mattext_incorrect.text = q['explanation']
        etree.SubElement(incorrect_resp, "displayfeedback", feedbacktype="Response", linkrefid="feedback_incorrect")

    tree = etree.ElementTree(qti)
    buf = io.BytesIO()
    tree.write(buf, pretty_print=True, xml_declaration=True, encoding='UTF-8')
    return buf.getvalue()

# --------- STREAMLIT APP --------- #

def main():
    st.set_page_config(page_title="QTI Converter - FUSE", layout="wide")
    st.title("QTI Converter - FUSE (Web Version)")

    st.write("Paste your questions, pick the formatting rules, and generate a QTI XML (and optional ZIP) for Canvas. 🧠📥➡️📤")

    col_left, col_right = st.columns([2, 1])

    with col_left:
        points = st.number_input(
            "Points per question",
            min_value=0.0,
            value=1.0,
            step=0.5
        )

        content = st.text_area(
            "Paste your questions here",
            height=400,
            placeholder="Example:\n\nQuestion 1: What is 2+2?\na) 3\n*b) 4\nc) 5\nAnswer: b) 4\nExplanation: 2+2 is 4."
        )

    with col_right:
        st.subheader("Format Assistant")

        q_start_label = st.selectbox(
            "1. How does each question start?",
            [
                "bold — e.g., **What is...?**",
                "question — e.g., Question 1:",
                "newline — e.g., separated by blank lines"
            ],
            index=2  # default: newline
        )

        opt_style_label = st.selectbox(
            "2. How are the options formatted?",
            [
                "A) — e.g., A) Option A",
                "a) — e.g., a) Option A",
                "· A) — e.g., · A) Option A",
                "1) — e.g., 1) Option A"
            ],
            index=1  # default: a)
        )

        answer_prefix = st.text_input(
            "3. What text starts the answer line?",
            value="Answer:"
        )

        explanation_prefix = st.text_input(
            "4. What text starts the explanation line?",
            value="Explanation:"
        )

        zip_opt = st.checkbox(
            "Also generate ZIP file for upload",
            value=True
        )

        convert_clicked = st.button("Convert to QTI")

    if convert_clicked:
        if not content.strip():
            st.error("🚫 Please paste the question text first.")
            return

        try:
            # Map selection labels to regex keys
            question_start_key = q_start_label.split(" —")[0].strip()
            option_style_key = opt_style_label.split(" —")[0].strip()

            q_sep_map = {
                'bold': r'\n(?=\*\*)',
                'question': r'\n(?=Question\s+\d+:)',
                'newline': r'\n\s*\n'
            }
            opt_regex_map = {
                'A)': r'^[A-D]\)',
                'a)': r'^[a-d]\)',
                '· A)': r'^\u00b7\s[A-D]\)',
                '1)': r'^\d+\)'
            }

            q_sep = q_sep_map[question_start_key]
            opt_regex = opt_regex_map[option_style_key]

            # Parse questions
            questions = parse_guided_format(
                content,
                q_sep=q_sep,
                opt_regex=opt_regex,
                answer_prefix=answer_prefix,
                explanation_prefix=explanation_prefix
            )

            st.success(f"✅ Parsed {len(questions)} questions successfully!")

            # Preview
            with st.expander("Preview parsed questions"):
                for i, q in enumerate(questions, start=1):
                    st.markdown(f"**Q{i}: {q['question']}**")
                    for opt in q['options']:
                        clean_opt = re.sub(r'^[A-Da-d1-9]+\)\s*', '', opt).strip()
                        is_correct = q['answer'].strip().lower() == clean_opt.strip().lower()
                        prefix = "✅ " if is_correct else "• "
                        st.write(f"{prefix}{opt}")
                    st.write(f"**Answer:** {q['answer']}")
                    st.write(f"**Explanation:** {q['explanation']}")
                    st.markdown("---")

            # Create QTI XML bytes
            xml_bytes = create_qti_bytes(questions, points_per_question=points)

            st.download_button(
                label="⬇️ Download QTI XML",
                data=xml_bytes,
                file_name="quiz.xml",
                mime="application/xml"
            )

            if zip_opt:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.writestr("quiz.xml", xml_bytes)
                zip_buffer.seek(0)

                st.download_button(
                    label="⬇️ Download ZIP (quiz.zip)",
                    data=zip_buffer,
                    file_name="quiz.zip",
                    mime="application/zip"
                )

        except Exception as e:
            st.error(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    main()
