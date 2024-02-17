import logging
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate

import anyio
import cython
from aiosmtplib import SMTP
from sqlalchemy import null, or_, select

from app.config import (
    SMTP_HOST,
    SMTP_MESSAGES_FROM,
    SMTP_NOREPLY_FROM,
    SMTP_NOREPLY_FROM_HOST,
    SMTP_PASS,
    SMTP_PORT,
    SMTP_SECURE,
    SMTP_USER,
)
from app.db import db_autocommit
from app.lib.date_utils import utcnow
from app.lib.translation import render, translation_context
from app.limits import MAIL_PROCESSING_TIMEOUT, MAIL_UNPROCESSED_EXPIRE, MAIL_UNPROCESSED_EXPONENT
from app.models.db.mail import Mail
from app.models.db.user import User
from app.models.mail_from_type import MailFromType
from app.services.user_token_email_reply_service import UserTokenEmailReplyService


def _validate_smtp_config():
    return SMTP_NOREPLY_FROM and SMTP_MESSAGES_FROM


if _validate_smtp_config():

    def _create_smtp_client(host: str, port: int, user: str, password: str, secure: bool):
        if secure:
            if port not in (465, 587):
                raise ValueError('SMTP_SECURE is enabled but SMTP_PORT is not 465 or 587')

            use_tls = port == 465
            start_tls = True if port == 587 else None
            return SMTP(host, port, user, password, use_tls=use_tls, start_tls=start_tls)
        else:
            return SMTP(host, port, user, password)

    _SMTP = _create_smtp_client(SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_SECURE)
else:
    logging.warning('SMTP is not configured, mail delivery is disabled')
    _SMTP = None


async def _send_smtp(mail: Mail) -> None:
    # TODO: deleted users
    # if not mail.to_user:
    #     logging.info('Discarding mail %r to user %d (not found)', mail.id, mail.to_user_id)
    #     return

    message = EmailMessage()

    if mail.from_type == MailFromType.system:
        message['From'] = SMTP_NOREPLY_FROM
    else:
        reply_address = await UserTokenEmailReplyService.create_address(
            replying_user_id=mail.to_user_id,
            source_type=mail.from_type,
        )
        message['From'] = formataddr((mail.from_user.display_name, reply_address))

    message['To'] = formataddr((mail.to_user.display_name, mail.to_user.email))
    message['Date'] = formatdate()
    message['Subject'] = mail.subject
    message.set_content(mail.body, subtype='html')

    if mail.ref:
        full_ref = f'<osm-{mail.ref}@{SMTP_NOREPLY_FROM_HOST}>'
        logging.debug('Setting mail %r reference to %r', mail.id, full_ref)
        message['In-Reply-To'] = full_ref
        message['References'] = full_ref

        # disables threading in gmail
        message['X-Entity-Ref-ID'] = full_ref

    if _SMTP is None:
        logging.info('Discarding mail %r (SMTP is not configured)', mail.id)
        return

    logging.debug('Sending mail %r', mail.id)
    await _SMTP.send_message(message)


class MailService:
    @staticmethod
    async def schedule(
        from_user: User | None,
        from_type: MailFromType,
        to_user: User,
        subject: str,
        template_name: str,
        template_data: dict,
        ref: str | None = None,
        priority: int = 0,
    ) -> None:
        """
        Schedule a mail for later processing.
        """

        # use destination user's preferred language
        with translation_context(to_user.languages):
            body = render(template_name, **template_data)

        async with db_autocommit() as session:
            mail = Mail(
                from_user_id=from_user.id if (from_user is not None) else None,
                from_type=from_type,
                to_user_id=to_user.id,
                subject=subject,
                body=body,
                ref=ref,
                priority=priority,
            )

            logging.debug('Scheduling mail %r to %d with subject %r', mail.id, to_user.id, subject)
            session.add(mail)

    @staticmethod
    async def process_scheduled() -> None:
        """
        Process the next scheduled mail.
        """

        async with db_autocommit() as session:
            now = utcnow()
            stmt = (
                select(Mail)
                .where(
                    or_(
                        Mail.processing_at == null(),
                        Mail.processing_at <= now,
                    )
                )
                .order_by(
                    Mail.processing_counter,
                    Mail.priority.desc(),
                    Mail.created_at,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )

            mail = await session.scalar(stmt)

            # nothing to do
            if mail is None:
                return

            try:
                logging.info('Processing mail %r to %d with subject %r', mail.id, mail.to_user.id, mail.subject)

                with anyio.fail_after(MAIL_PROCESSING_TIMEOUT.total_seconds() - 5):
                    await _send_smtp(mail)

                await session.delete(mail)

            except Exception:
                expires_at = mail.created_at + MAIL_UNPROCESSED_EXPIRE
                processing_at = now + timedelta(minutes=mail.processing_counter**MAIL_UNPROCESSED_EXPONENT)

                if expires_at <= processing_at:
                    logging.warning(
                        'Expiring unprocessed mail %r, created at: %r',
                        mail.id,
                        mail.created_at,
                        exc_info=True,
                    )
                    await session.delete(mail)
                    return

                logging.info('Requeuing unprocessed mail %r', mail.id, exc_info=True)
                mail.processing_counter += 1
                mail.processing_at = processing_at
