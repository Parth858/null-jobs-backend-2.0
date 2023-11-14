import re
import uuid
import logging

from django.core.exceptions import ValidationError
from django.core.validators import (
    EmailValidator,
    MaxValueValidator,
    MinValueValidator,
    URLValidator,
)


class validationClass:
    """
    This class provides validation functionality for files such as resumes and images.
    Currently supports validation for:
    1. Resume files
    2. Image files
    """

    logger = logging.getLogger("jobs.ValidationClass")

    @staticmethod
    def is_valid_uuid(value):
        # Expects value in proper format(with hyphens) of uuid, returns bool value
        try:
            uuid_value = uuid.UUID(str(value))
        except ValueError:
            validationClass.logger.error("The specified value is not a valid uuid")
            return False
        else:
            if str(uuid_value) == str(value):
                return True
            else:
                # Log an error when the UUID value is not the same as the input
                validationClass.logger.error(
                    f"Mismatch between input and UUID value: {value}"
                )
                return False

    @staticmethod
    def validate_id(uuid, idtype: str, model_class):
        """perform checks on uuid, and if it
        exists in the database."""
        validationClass.logger.info("validating the id type")
        if not validationClass.is_valid_uuid(uuid):
            validationClass.logger.error(f"{idtype} isn't a valid UUID")
            return {"error": f"{idtype} isn't a valid UUID"}

        if model_class.objects.filter(pk=uuid).count() < 1:
            validationClass.logger.error(f"This {idtype} doesn't exist")
            return {"error": f"This {idtype} doesn't exist"}

    def image_validation(self, image_file):
        # check size
        filesize = image_file.size / (1024 * 1024)
        if filesize > 10:
            validationClass.logger.warning(f"Profile image exceeds 10mb")
            return (False, "Profile Image shouldn't exceed 10mb")

        allowed_image_extensions = ["png", "jpeg", "jpg"]
        allowed_content_types = ["image/png", "image/jpg", "image/jpeg"]
        image_file_extension = image_file.name.split(".")[-1].lower()
        upload_file_to_storage = False

        # filename check
        if not re.match("[\w\-]+\.\w{3,4}$", image_file.name):
            validationClass.logger.error("Image File name isn't appropriate")
            return (False, "Image File name isn't appropriate")

        # Allowed content-type/extensions check
        validationClass.logger.info(f"Checking image extension: {image_file_extension}")
        if (
            image_file_extension in allowed_image_extensions
            and image_file.content_type in allowed_content_types
        ):
            # check signatures
            if (image_file_extension == "png") and (
                image_file.file.read()[:8].hex().upper().encode("ASCII")
                == "89504E470D0A1A0A".encode("ASCII")
            ):
                upload_file_to_storage = True
            elif (image_file_extension in ["jpg", "jpeg"]) and (
                image_file.file.read()[:8].hex().upper().startswith("FFD8")
            ):
                upload_file_to_storage = True
            else:
                validationClass.logger.error(f"{image_file} type isn't supported")
                return (False, "Image File type isn't supported")
        else:
            validationClass.logger.error("Wrong image file submitted")
            return (False, "Oops, Wrong image file submitted")

        if upload_file_to_storage:
            validationClass.logger.info("File is valid")
            return (True, "File is valid")

    def resume_validation(self, resume_file):
        # check size (shouldn't exceed 10mb)
        filesize = resume_file.size / (1024 * 1024)
        if filesize > 10:
            validationClass.logger.error(f"Resume file exceed's 10mb")
            return (False, "Resume File size shouldn't exceed 10mb")
        else:
            ## check characters present in the file name
            # for example: Only allowed those files that
            # includes only alphanumeric, hyphen and a period
            if not re.match("[\w\-]+\.\w{3,4}$", resume_file.name):
                validationClass.logger.error(f"{resume_file} name isn't appropriate")
                return (False, "Resume File name isn't appropriate")

            # check file extension & content_type
            upload_file_to_storage = False
            allowed_file_extensions = ["pdf", "docx", "doc"]
            allowed_content_types = [
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ]
            file_extension = resume_file.name.split(".")[-1].lower()
            if (
                file_extension in allowed_file_extensions
                and resume_file.content_type in allowed_content_types
            ):
                # check file signature thing
                if file_extension == "pdf":
                    if resume_file.file.read()[:4].hex().upper().encode(
                        "ASCII"
                    ) == "25504446".encode("ASCII"):
                        upload_file_to_storage = True
                elif file_extension == "docx":
                    if resume_file.file.read()[:4].hex().upper().encode(
                        "ASCII"
                    ) == "504B0304".encode("ASCII"):
                        upload_file_to_storage = True
                elif file_extension == "doc":
                    if resume_file.file.read()[:4].hex().upper().encode(
                        "ASCII"
                    ) == "D0CF11E0A1B11AE1".encode("ASCII"):
                        upload_file_to_storage = True
                else:
                    validationClass.logger.error(f"Resume file name is not supported")
                    return (False, "Resume File type is not supported")
            else:
                validationClass.logger.error(f"Wrong {resume_file} submitted")
                return (False, "Oops, wrong resume file submitted")

        if upload_file_to_storage:
            validationClass.logger.info("File is valid")
            return (True, "File is valid")

    @staticmethod
    def validate_fields(data):
        """
        This method is used to validate some specific fields
        present in the given data (format: dictionary)
        """
        validationClass.logger.info("Validationing fields")
        for field_name, field_value in data.items():
            try:
                if field_name == "age":
                    MinValueValidator(15)(field_value)
                    MaxValueValidator(100)(field_value)
                if field_name == "email":
                    EmailValidator()(field_value)
                if field_name == "website":
                    if not re.search("^(https?|ftp)://[^\s/$.?#].[^\s]*$", field_value):
                        validationClass.logger.error(
                            f"Invalid {field_name} provided: {field_value}"
                        )
                        raise Exception(f"Invalid {field_name} value provided")
                if field_name == "experience":
                    # Here, if the experience value exceeds 15, replace the value
                    # with "15+", Also check if there are only two integers given
                    # by the user, and these two integers should be positive & <= 15

                    # check if experience value contains two integers
                    if re.search("^\d\d$", field_value):
                        # check if the matched integer value greater than 15
                        if re.search("^(1[6-9]|[2-9][0-9])$", field_value):
                            data[field_name] = "15+"
                    else:
                        validationClass.logger.error(
                            f"Invalid {field_name} value provided"
                        )
                        raise Exception(f"Invalid {field_name} value provided")

            except (Exception, ValidationError) as err:
                validationClass.logger.error(
                    f"Given {field_name} doesn't contain a valid value\n\nReason: {err.__str__()}"
                )
                raise Exception(
                    f"Given {field_name} doesn't contain a valid value\n\nReason: {err.__str__()}"
                )
