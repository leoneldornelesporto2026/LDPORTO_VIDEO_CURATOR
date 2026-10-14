"""Interview composition decisions use explicit relevance, not random duplication."""


def choose_layout(faces, relevant_people, union_safe=False, reaction_person=None, reaction_evidence=False):
    visible = {row.get('person_id') for row in faces if row.get('face_bbox')}
    relevant = [person for person in dict.fromkeys(relevant_people) if person in visible]
    if not relevant:
        return {'layout': 'source_preserve', 'people': [], 'reason': 'NO_RELEVANT_VISIBLE_TARGET'}
    if len(relevant) == 1 and reaction_evidence and reaction_person in visible and reaction_person != relevant[0]:
        return {'layout': 'speaker_reaction', 'people': [relevant[0], reaction_person], 'reason': 'OBSERVED_LISTENER_REACTION'}
    if len(relevant) == 1:
        return {'layout': 'single_speaker', 'people': relevant, 'reason': 'ONE_RELEVANT_TARGET'}
    return {'layout': 'two_shot' if union_safe else 'split_screen', 'people': relevant[:2],
            'reason': 'SAFE_UNION' if union_safe else 'RELEVANT_TARGETS_REQUIRE_SEPARATE_CROPS'}
