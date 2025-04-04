"""
Model Context Protocol (MCP) implementation for email connectivity in MailoBot
"""
import imaplib
import email
import json
import os
import re
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Any, Optional, Text

# Increase the default timeout for IMAP connections
imaplib._MAXLINE = 1000000
class EmailMCP:
    """
    A Model Context Protocol implementation for email connectivity
    Maintains context about email sessions and provides methods for email operations
    """

    def __init__(self, settings: Optional[Dict[str, Any]] = None):
        """
        Initialize the EmailMCP with optional settings
        
        Args:
            settings: Dictionary with IMAP settings (host, port, username, password, tls)
        """
        self.imap_conn = None
        self.settings = settings
        self.context = {
            "connected": False,
            "mailbox": None,
            "current_folder": "INBOX",
            "recent_emails": [],
            "unread_count": 0,
            "selected_email": None
        }
        
        # If no settings provided, try to load from JSON file
        if not self.settings:
            self.load_settings_from_file()

    def load_settings_from_file(self):
        """Load IMAP settings from JSON file if available"""
        try:
            # Get the path relative to the current file
            current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            settings_file = os.path.join(current_dir, 'settings', 'imap_settings.json')
            
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    self.settings = json.load(f)
                print("Loaded IMAP settings from file")
            else:
                print("Settings file not found: {}".format(settings_file))
        except Exception as e:
            print(f"Error loading settings from file: {e}")

    def connect(self, settings: Optional[Dict[str, Any]] = None):
        """
        Connect to the email server using IMAP
        
        Args:
            settings: Dictionary with IMAP settings (can override init settings)
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        if settings:
            self.settings = settings
        elif not self.settings:
            # Try to load settings from file if not already set
            self.load_settings_from_file()

        if not self.settings:
            raise ValueError("Email settings not provided")

        try:
            # Connect to the IMAP server
            if self.settings.get('tls', True):
                self.imap_conn = imaplib.IMAP4_SSL(
                    self.settings['host'], int(self.settings.get('port', 993)))
            else:
                self.imap_conn = imaplib.IMAP4(
                    self.settings['host'], int(self.settings.get('port', 143)))

            # Login with credentials
            self.imap_conn.login(
                self.settings['username'], self.settings['password'])

            # Update context
            self.context["connected"] = True
            return True

        except Exception as e:
            print(f"Error connecting to email server: {e}")
            self.context["connected"] = False
            self.context["error"] = str(e)
            return False

    def disconnect(self):
        """Close the IMAP connection if active"""
        if self.imap_conn:
            try:
                self.imap_conn.logout()
            except:
                pass
            self.imap_conn = None
            self.context["connected"] = False

    def select_folder(self, folder: str = "INBOX"):
        """
        Select a mailbox folder
        
        Args:
            folder: Mailbox folder name
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            return False

        try:
            status, data = self.imap_conn.select(folder)
            if status == "OK":
                self.context["current_folder"] = folder
                self.context["mailbox"] = data
                return True
            return False
        except Exception as e:
            print(f"Error selecting folder {folder}: {e}")
            return False

    def is_connected(self):
        """Check if connected to email server"""
        return self.imap_conn is not None and self.context.get("connected", False)

    def get_unread_count(self):
        """Get the number of unread emails in the current folder"""
        if not self.is_connected():
            return 0

        try:
            self.select_folder(self.context["current_folder"])
            status, data = self.imap_conn.search(None, 'UNSEEN')
            if status == "OK":
                unread_ids = data[0].split()
                count = len(unread_ids)
                self.context["unread_count"] = count
                return count
            return 0
        except Exception as e:
            print(f"Error getting unread count: {e}")
            return 0

    def get_recent_emails(self, limit: int = 5):
        """
        Get the most recent emails
        
        Args:
            limit: Maximum number of emails to retrieve
            
        Returns:
            List of email dictionaries
        """
        if not self.is_connected():
            print("Cannot get recent emails - not connected")
            return []

        try:
            self.select_folder(self.context["current_folder"])
            status, data = self.imap_conn.search(None, 'ALL')
            if status != "OK":
                print(f"Search failed with status: {status}")
                return []

            email_ids = data[0].split()

            if not email_ids:
                print("No email IDs found in folder")
                return []

            # Get the most recent emails (last N emails)
            recent_ids = email_ids[-limit:] if len(
                email_ids) > limit else email_ids
            recent_ids.reverse()  # Most recent first

            print(
                f"Found {len(recent_ids)} recent emails out of {len(email_ids)} total")

            emails = []
            for email_id in recent_ids:
                email_data = self.fetch_email(email_id)
                if email_data:
                    emails.append(email_data)

            # Update context
            self.context["recent_emails"] = emails
            print(f"Updated context with {len(emails)} emails")
            return emails
        except Exception as e:
            print(f"Error getting recent emails: {e}")
            return []

    def fetch_email(self, email_id):
        """
        Fetch a single email by ID
        
        Args:
            email_id: Email ID to fetch
            
        Returns:
            Email data dictionary or None if error
        """
        if not self.is_connected():
            return None

        try:
            status, data = self.imap_conn.fetch(email_id, '(RFC822)')
            if status != "OK" or not data[0]:
                print(f"Failed to fetch email {email_id}: {status}")
                return None

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Extract headers
            subject = self._decode_header(msg["Subject"])
            from_header = self._decode_header(msg["From"])
            to_header = self._decode_header(msg.get("To", ""))
            date = msg["Date"]

            # Extract email address from the From header
            sender = from_header
            if '<' in from_header and '>' in from_header:
                sender = re.search(r'<([^>]+)>', from_header).group(1)

            # Extract body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))

                    # Skip attachments
                    if "attachment" in content_disposition:
                        continue

                    # Get text content
                    if content_type == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode()
                            break
                        except Exception as e:
                            print(f"Error decoding email body: {e}")
                            body = "Error: Could not decode email body"
                            pass
                    elif content_type == "text/html" and not body:
                        try:
                            # Simple HTML to text conversion - if needed, enhance this
                            html = part.get_payload(decode=True).decode()
                            # Simple HTML tag removal
                            body = re.sub('<[^<]+?>', ' ', html)
                        except Exception as e:
                            print(f"Error processing HTML body: {e}")
                            pass
            else:
                try:
                    body = msg.get_payload(decode=True).decode()
                except Exception as e:
                    print(f"Error decoding single-part message: {e}")
                    body = "Unable to decode message body"

            # Extract attachments
            attachments = []
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_maintype() == 'multipart':
                        continue
                    if part.get('Content-Disposition') is None:
                        continue

                    filename = part.get_filename()
                    if filename:
                        attachments.append({
                            'filename': filename,
                            'content_type': part.get_content_type()
                        })

            # Check read status
            status, read_data = self.imap_conn.fetch(email_id, '(FLAGS)')
            read = b'\\Seen' in read_data[0]

            # Format the email ID for consistency
            email_id_str = email_id.decode() if isinstance(
                email_id, bytes) else str(email_id)

            email_data = {
                "id": email_id_str,
                "message_id": msg.get("Message-ID", f"msg_{email_id_str}"),
                "subject": subject,
                "from": sender,
                "to": to_header,
                "date": date,
                "body": body,
                "read": read,
                "has_attachments": len(attachments) > 0,
                "attachments": attachments,
                "folder": self.context["current_folder"]
            }

            return email_data
        except Exception as e:
            print(f"Error fetching email {email_id}: {e}")
            return None

    def _decode_header(self, header):
        """
        Decode email header
        
        Args:
            header: Email header to decode
            
        Returns:
            Decoded header string
        """
        if not header:
            return ""

        try:
            decoded_header = decode_header(header)
            header_parts = []

            for part, encoding in decoded_header:
                if isinstance(part, bytes):
                    try:
                        if encoding:
                            header_parts.append(part.decode(encoding))
                        else:
                            header_parts.append(part.decode(
                                'utf-8', errors='replace'))
                    except:
                        # Fallback to safe decoding
                        header_parts.append(part.decode(
                            'ascii', errors='replace'))
                else:
                    header_parts.append(part)

            return " ".join(header_parts)
        except Exception as e:
            print(f"Error decoding header: {e}")
            # Return original as fallback
            return header if header else ""

    def mark_as_read(self, email_id):
        """Mark an email as read"""
        if not self.is_connected():
            return False

        try:
            self.imap_conn.store(email_id, '+FLAGS', '\\Seen')
            return True
        except Exception as e:
            print(f"Error marking email as read: {e}")
            return False

    def search_emails(self, criteria: Dict[str, Any]):
        """
        Search for emails using various criteria
        
        Args:
            criteria: Dictionary with search parameters (sender, subject, date, etc.)
            
        Returns:
            List of email dictionaries matching criteria
        """
        if not self.is_connected():
            return []

        try:
            search_query = []

            if 'sender' in criteria:
                search_query.append(f'FROM "{criteria["sender"]}"')

            if 'subject' in criteria:
                search_query.append(f'SUBJECT "{criteria["subject"]}"')

            if 'since' in criteria:
                search_query.append(f'SINCE "{criteria["since"]}"')

            if 'unread' in criteria and criteria['unread']:
                search_query.append('UNSEEN')

            if 'has_attachments' in criteria and criteria['has_attachments']:
                search_query.append('BODY "Content-Disposition: attachment"')

            # Convert the query to IMAP format
            query = ' '.join(search_query)

            # Execute search
            self.select_folder(self.context["current_folder"])
            status, data = self.imap_conn.search(None, query)
            if status != "OK":
                return []

            email_ids = data[0].split()

            # Limit results
            limit = criteria.get('limit', 10)
            if len(email_ids) > limit:
                email_ids = email_ids[:limit]

            # Fetch emails
            results = []
            for email_id in email_ids:
                email_data = self.fetch_email(email_id)
                if email_data:
                    results.append(email_data)

            return results
        except Exception as e:
            print(f"Error searching emails: {e}")
            return []

    def get_context(self):
        """Get the current MCP context"""
        return self.context

    def update_context(self, updates: Dict[str, Any]):
        """
        Update the MCP context
        
        Args:
            updates: Dictionary with context updates
        """
        self.context.update(updates)

    def get_unread_emails(self, limit: int = 5):
        """
        Get unread emails from the current folder
        
        Args:
            limit: Maximum number of unread emails to retrieve
            
        Returns:
            List of unread email objects
        """
        if not self.is_connected():
            print("Not connected to email server")
            return []
            
        try:
            # Search for unread emails
            status, data = self.imap_conn.search(None, 'UNSEEN')
            if status != 'OK':
                print("Error searching for unread emails")
                return []
                
            email_ids = data[0].split()
            if not email_ids:
                print("No unread emails found")
                return []
                
            # Get most recent unread emails
            email_ids = email_ids[-min(limit, len(email_ids)):]
            
            # Fetch unread emails
            emails = []
            for email_id in email_ids:
                try:
                    email_data = self.fetch_email(email_id)
                    if email_data:
                        emails.append(email_data)
                except Exception as e:
                    print(f"Error fetching email {email_id}: {e}")
            
            # Update context
            self.context["unread_emails"] = emails
            return emails
            
        except Exception as e:
            print(f"Error getting unread emails: {e}")
            return []

    def save_draft(self, draft_data: Dict[str, Any]) -> bool:
        """
        Save a draft email to the IMAP server
        
        Args:
            draft_data: Dictionary with email draft data (to, subject, body, etc.)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            print("Not connected to email server")
            return False
            
        try:
            # Select drafts folder (create if not exists)
            drafts_folder = "Drafts"
            if not self.select_folder(drafts_folder):
                # Try different common names for drafts folder
                for folder_name in ["Draft", "DRAFTS", "Drafts", "[Gmail]/Drafts"]:
                    if self.select_folder(folder_name):
                        drafts_folder = folder_name
                        break
                else:
                    print(f"Could not find or create drafts folder")
                    return False
            
            # Create email message
            msg = MIMEMultipart()
            msg['From'] = draft_data.get('from', self.settings['username'])
            msg['To'] = draft_data.get('to', '')
            msg['Subject'] = draft_data.get('subject', '')
            
            # Add body
            body = draft_data.get('body', '')
            msg.attach(MIMEText(body, 'plain'))
            
            # Convert to string
            raw_message = msg.as_string()
            
            # Save to drafts folder
            result = self.imap_conn.append(drafts_folder, '\\Draft', None, raw_message.encode('utf-8'))
            
            if result[0] == 'OK':
                print(f"Draft saved to {drafts_folder} folder")
                # Update context
                if not self.context.get('drafts'):
                    self.context['drafts'] = []
                
                self.context['drafts'].append(draft_data)
                return True
            else:
                print(f"Failed to save draft: {result}")
                return False
                
        except Exception as e:
            print(f"Error saving draft: {e}")
            self.context['error'] = str(e)
            return False

    def send_email(self, email_data: Dict[str, Any]) -> bool:
        """
        Send an email using SMTP
        
        Args:
            email_data: Dictionary with email data (to, subject, body, etc.)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.settings:
            print("No email settings available")
            self.context['error'] = "No email settings available"
            return False
            
        try:
            # Create email message
            msg = MIMEMultipart()
            msg['From'] = email_data.get('from', self.settings['username'])
            msg['To'] = email_data.get('to', '')
            msg['Subject'] = email_data.get('subject', '')
            
            # Add body
            body = email_data.get('body', '')
            msg.attach(MIMEText(body, 'plain'))
            
            # Determine SMTP settings based on IMAP settings
            smtp_host = self.settings.get('smtp_host') or self.settings['host'].replace('imap', 'smtp')
            smtp_port = self.settings.get('smtp_port') or 587  # Default to 587 for TLS
            
            # Create SMTP connection
            if self.settings.get('tls', True):
                smtp_conn = smtplib.SMTP(smtp_host, smtp_port)
                smtp_conn.starttls()
            else:
                smtp_conn = smtplib.SMTP(smtp_host, smtp_port)
            
            # Login with credentials
            smtp_conn.login(self.settings['username'], self.settings['password'])
            
            # Send email
            to_list = [addr.strip() for addr in email_data.get('to', '').split(',') if addr.strip()]
            if not to_list:
                raise ValueError("No recipients specified")
                
            smtp_conn.sendmail(
                msg['From'],
                to_list,
                msg.as_string()
            )
            
            # Close connection
            smtp_conn.quit()
            
            print(f"Email sent successfully to {msg['To']}")
            
            # Update context
            sent_email = {
                "to": email_data.get('to', ''),
                "subject": email_data.get('subject', ''),
                "body": email_data.get('body', ''),
                "from": email_data.get('from', self.settings['username']),
                "timestamp": email_data.get('timestamp', ''),
                "folder": "sent"
            }
            
            if not self.context.get('sent_emails'):
                self.context['sent_emails'] = []
                
            self.context['sent_emails'].append(sent_email)
            return True
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error sending email: {error_msg}")
            self.context['error'] = error_msg
            return False
