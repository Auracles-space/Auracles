

async def test_a_phone_already_gone_is_not_an_error_to_close_on(db, funded_account):
    """Hanging up is how rooms end, and it must not surface as a crash.

    The last thing the route does is close the socket. If the phone has already
    dropped — which is what *caused* the room to end in the ordinary case — the
    close raises `WebSocketDisconnect`, and with nothing catching it the room
    ends in an unhandled ASGI traceback. Everything downstream is already
    correct at that point: the session settled, the minutes are right, the cost
    row is written. Only the log is wrong.

    Worth fixing rather than tolerating, because a traceback that appears on
    every normal ending is a traceback nobody reads — and the next real one
    arrives in the middle of a hundred of these.
    """

    class Vanished(FakeWebSocket):
        async def close(self, code: int = 1000) -> None:
            await super().close(code)
            raise WebSocketDisconnect(code=1006)

    session, ticket = await _admitted(db, funded_account, archetypes=["cfo"])
    websocket = Vanished()

    await stream_session(
        websocket,
        session.id,
        ticket,
        VoiceTicketService(db),
        RoomParts(
            transcriber=FakeTranscriber(),
            model=FakePanelModel(selects="cfo"),
            speaker=None,
        ),
        db,
    )

    await db.refresh(session)
    assert session.state is SessionState.SETTLED
