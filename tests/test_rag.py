from backend.rag import retrieve_relevant_chunks


def test_retrieve_relevant_chunks_returns_library_services_for_library_question() -> None:
    chunks = retrieve_relevant_chunks("What are the library hours and borrowing rules?")
    assert chunks
    assert any(chunk["title"] == "Library Services" for chunk in chunks)


def test_retrieve_relevant_chunks_returns_hostel_application_for_hostel_question() -> None:
    chunks = retrieve_relevant_chunks("How do I apply for hostel accommodation?")
    assert chunks
    assert any(chunk["title"] == "Hostel Application" for chunk in chunks)


def test_retrieve_relevant_chunks_returns_empty_for_unrelated_question() -> None:
    chunks = retrieve_relevant_chunks("What is the weather like on Mars?")
    assert chunks == []


def test_retrieve_relevant_chunks_handles_synonyms_like_myuni() -> None:
    # 'myuni' is a common user term; ensure synonym mapping finds ARIS3/course registration
    chunks = retrieve_relevant_chunks("How do I register using myuni?")
    assert chunks
    assert any(chunk["title"] == "Course Registration" for chunk in chunks)


def test_retrieve_relevant_chunks_returns_hostel_info_for_coict_query() -> None:
    # CoICT hostel pricing query should return Hostel Application chunk
    chunks = retrieve_relevant_chunks("I want the exact price for CoICT hostels")
    assert chunks
    assert any(chunk["title"] == "Hostel Application" for chunk in chunks)
