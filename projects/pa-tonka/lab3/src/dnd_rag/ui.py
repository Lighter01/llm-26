"""Single-current-question Streamlit client. All model work belongs to the HTTP API."""

import os

import httpx
import streamlit as st


def _pages(section):
    pages = section.get('printed_pages')
    if not pages:
        return 'The source gives no printed page for this section.'
    label = 'printed page' if len(pages) == 1 else 'printed pages'
    location = f'{label} {" and ".join(map(str, pages))}'
    attribution = section['page_attribution']
    if attribution == 'inherited_section_start':
        return f'The enclosing section starts on {location}. The exact page of this passage is unknown.'
    if attribution == 'partial':
        return f'Only part of this section has known page numbers ({location}).'
    return f'This section includes material from {location}.'


def _show_result(result):
    st.subheader(result['question'])
    st.markdown(result['answer'])
    timings = result['timings_ms']
    generation = timings.get('generation')
    generation_text = f'{generation / 1000:.2f} s' if generation is not None else 'skipped'
    st.caption(f'Total: {timings["total"] / 1000:.2f} s · Generation: {generation_text}')
    for warning in result['warnings']:
        st.warning(warning['message'])
    if not result['sources']:
        st.caption('No valid source citations in this answer.')
    for source in result['sources']:
        with st.expander(f'[{source["citation_id"]}] {source["book_title"]}'):
            st.caption(
                f'{source["source_file"]} · Markdown lines {source["line_start"]}–{source["line_end"]} '
                '(line 1 is the first line of book text after the metadata header)'
            )
            for section in source['sections']:
                st.text(' > '.join(section['heading_path']))
                st.caption(_pages(section))
            st.caption('Passage preview')
            st.text(source['snippet'] + ('…' if source['snippet_truncated'] else ''))
            st.caption('Full original passage')
            # Streamlit removes one boundary newline; padding keeps copied raw text exact.
            st.code('\n' + source['page_content'] + '\n', language='markdown', wrap_lines=True)


def _qa_notice(api):
    unavailable = (
        'Could not check the local API. Check that the demo is running, then refresh this page.'
    )
    try:
        health = httpx.get(api + '/health', timeout=3)
        if health.status_code not in (200, 503):
            return unavailable
        state = health.json()
    except (httpx.HTTPError, ValueError):
        return unavailable
    if not isinstance(state, dict) or not isinstance(state.get('qa_ready'), bool):
        return unavailable
    if state.get('mode') == 'retrieval_only':
        return 'The API is in search-only mode. Stop the search service and start the demo to ask questions.'
    if health.status_code == 200 and state['qa_ready']:
        return None
    return (
        'Q&A is not ready. Check the demo terminal for progress or errors, then refresh this page.'
    )


def main():
    st.set_page_config(page_title='D&D Rules Q&A', page_icon='🎲')
    st.title('D&D Rules Q&A')
    st.caption('Ask in English. Answers use passages from the three core rulebooks.')
    api = os.environ.get('RAG_API_URL', 'http://127.0.0.1:8000').rstrip('/')
    notice = _qa_notice(api)
    if notice:
        st.warning(notice)
    with st.form('question_form'):
        question = st.text_area('Your rules question', key='question', height=130)
        submitted = st.form_submit_button('Ask', disabled=notice is not None)
    if submitted:
        st.session_state.pop('current_result', None)
        if not question.strip():
            st.error('Enter a question.')
        else:
            with st.spinner('Finding rules and preparing an answer…'):
                try:
                    response = httpx.post(api + '/ask', json={'question': question}, timeout=180)
                    payload = response.json()
                    if response.status_code == 200:
                        st.session_state['current_result'] = payload
                    else:
                        st.error(payload.get('error', {}).get('message', 'The request failed.'))
                except httpx.TimeoutException:
                    st.error('The request timed out. Check the local service before retrying.')
                except (httpx.HTTPError, ValueError):
                    st.error('The local service is unavailable or returned an invalid response.')
    if 'current_result' in st.session_state:
        _show_result(st.session_state['current_result'])


if __name__ == '__main__':
    main()
