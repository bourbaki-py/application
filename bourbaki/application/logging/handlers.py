# coding: utf-8
from operator import attrgetter
import multiprocessing
import threading
import logging
import sys
import traceback
from getpass import getpass
import smtplib
import email.utils
from email.message import EmailMessage
from logging import StreamHandler, ERROR, LogRecord
from logging.handlers import SMTPHandler, MemoryHandler, RotatingFileHandler
from .config import validate_log_level_int


class BufferingSMTPHandler(MemoryHandler):
    def __init__(
        self,
        capacity,
        mailhost,
        toaddrs,
        subject=None,
        flushLevel=ERROR,
        *,
        credentials=None,
        fromaddr=None,
        secure=None,
        mailport=None,
        timeout=5.0
    ):
        flushLevel = validate_log_level_int(flushLevel)

        if isinstance(credentials, str):
            credentials = (
                credentials,
                getpass("Please enter a password for {}: ".format(credentials)),
            )

        if fromaddr is None:
            if not isinstance(credentials, (list, tuple)) or len(credentials) != 2:
                raise ValueError(
                    "you must supply either fromaddr or credentials=(uername, password); "
                    "fromaddr is None but credentials = {}".format(credentials)
                )
            fromaddr = credentials[0]

        if isinstance(toaddrs, str):
            toaddrs = [toaddrs]
        elif not toaddrs:
            raise ValueError(
                "you must supply toaddrs, either a single email address or a list thereof"
            )

        if mailport is not None:
            # SMTPHandler uses a tuple for this
            mailhost = (mailhost, mailport)
        elif not isinstance(mailhost, (list, tuple)) or len(mailhost) != 2:
            raise ValueError(
                "If mailport is not explicitly passed, mailhost must be a (host, port) tuple; got {}".format(
                    mailhost
                )
            )

        MemoryHandler.__init__(self, capacity, flushLevel=flushLevel)
        SMTPHandler.__init__(
            self,
            mailhost=mailhost,
            fromaddr=fromaddr,
            toaddrs=toaddrs,
            subject=subject,
            credentials=credentials,
            secure=secure,
            timeout=timeout,
        )

    def send_mail(self, content, subject=None):
        msg = EmailMessage()
        msg["From"] = self.fromaddr
        msg["To"] = ",".join(self.toaddrs)
        subject = subject or self.subject
        if subject is not None:
            msg["Subject"] = subject
        msg["Date"] = email.utils.localtime()
        msg.set_content(content)

        port = self.mailport or smtplib.SMTP_PORT
        smtp = smtplib.SMTP(self.mailhost, port, timeout=self.timeout)
        try:
            if self.username:
                if self.secure is not None:
                    smtp.ehlo()
                    smtp.starttls(*self.secure)
                    smtp.ehlo()
                smtp.login(self.username, self.password)
            smtp.send_message(msg)
        finally:
            smtp.quit()

    def get_content(self):
        return "\n".join(map(self.format, self.buffer))

    def get_subject(self):
        if self.subject:
            return self.subject
        top_record = max(self.buffer, key=attrgetter("levelno"))
        top_records = [r for r in self.buffer if r.levelno >= top_record.levelno]
        names = sorted(set(r.name for r in top_records))
        return "{} messages from loggers {}".format(
            top_record.levelname, ", ".join(names)
        )

    def flush(self):
        if len(self.buffer) > 0:
            content = self.get_content()
            subject = self.get_subject()

            try:
                self.send_mail(content, subject)
            except:
                self.handleError(
                    LogRecord(
                        self.name,
                        self.level,
                        pathname=None,
                        lineno=None,
                        msg=content,
                        args=(),
                        exc_info=sys.exc_info(),
                    )
                )  # no particular record
            finally:
                self.buffer = []

    def __del__(self):
        self.flush()


class MultiProcHandler(logging.Handler):
    """
    Adapted from zzzeek's answer at:
    https://stackoverflow.com/questions/641420/how-should-i-log-while-using-multiprocessing-in-python
    Tweaked and subclassed here - added the get_subhandler() method for generality.
    """

    subhandler_cls = None

    def __init__(self, *args, **kwargs):
        logging.Handler.__init__(self)

        self._handler = self.get_subhandler(*args, **kwargs)
        self.queue = multiprocessing.Queue(-1)

        t = threading.Thread(target=self.receive, daemon=True)
        t.start()

    def get_subhandler(self, *args, **kwargs):
        return self.subhandler_cls(*args, **kwargs)

    def setFormatter(self, fmt):
        logging.Handler.setFormatter(self, fmt)
        self._handler.setFormatter(fmt)

    def receive(self):
        while True:
            try:
                record = self.queue.get()
                self._handler.emit(record)
            except (KeyboardInterrupt, SystemExit):
                raise
            except EOFError:
                break
            except:
                traceback.print_exc(file=sys.stderr)

    def send(self, s):
        self.queue.put_nowait(s)

    def _format_record(self, record):
        # ensure that exc_info and args
        # have been stringified.  Removes any chance of
        # unpickleable things inside and possibly reduces
        # message size sent over the pipe
        if record.args:
            record.msg = record.msg % record.args
            record.args = None
        if record.exc_info:
            dummy = self.format(record)
            record.exc_info = None

        return record

    def emit(self, record):
        try:
            s = self._format_record(record)
            self.send(s)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)

    def close(self):
        self._handler.close()
        logging.Handler.close(self)

    def __del__(self):
        self.close()


class MultiProcRotatingFileHandler(MultiProcHandler):
    subhandler_cls = RotatingFileHandler

    def __init__(self, filename, mode="a", maxBytes=2 ** 20, backupCount=0):
        super().__init__(filename, mode, maxBytes, backupCount)


class MultiProcStreamHandler(MultiProcHandler):
    subhandler_cls = StreamHandler

    def __init__(self, stream):
        super().__init__(stream)


class MultiProcBufferingSMTPHandler(MultiProcHandler):
    subhandler_cls = BufferingSMTPHandler

    def __init__(
        self,
        capacity,
        mailhost,
        toaddrs,
        subject=None,
        flushLevel=ERROR,
        *,
        credentials=None,
        fromaddr=None,
        secure=None,
        mailport=None,
        timeout=5.0
    ):
        super().__init__(
            capacity=capacity,
            mailhost=mailhost,
            toaddrs=toaddrs,
            subject=subject,
            flushLevel=flushLevel,
            credentials=credentials,
            fromaddr=fromaddr,
            secure=secure,
            mailport=mailport,
            timeout=timeout,
        )
